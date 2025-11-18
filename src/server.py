import os
import re
from sqlalchemy import func, case
from sqlalchemy.orm import selectinload
from flask import g, Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from redis import Redis
from rq import Queue
from rq.registry import FailedJobRegistry
from .database import (
    get_session,
    Repository,
    Scan,
    Finding,
    Patch,
    ChatMessage,
    QualityMetric,
    QualityInterpretation,
    ScanStatus,
)
from .orchestrator import Orchestrator
from .vcs import VCSService
from .llm import LLMService
from . import config
from . import di
from .validators import (
    RepositoryUrlInput,
    RepositoryConfirmInput,
    ScanConfigInput,
    PeriodicScanInput,
    CIScanInput,
    validate_input,
)

app = Flask(__name__, static_folder="static")
app.secret_key = os.urandom(24)

# Initialize CSRF protection
csrf = CSRFProtect(app)

redis_host = os.getenv("REDIS_HOST", "localhost")
redis_port = int(os.getenv("REDIS_PORT", "6379"))
redis_conn = Redis(host=redis_host, port=redis_port)
q = Queue(connection=redis_conn, default_timeout=3600)

# Initialize rate limiter with Redis backend
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri=f"redis://{redis_host}:{redis_port}",
    default_limits=["200 per hour", "50 per minute"],
    storage_options={"socket_connect_timeout": 30},
    strategy="fixed-window",
)

try:
    from googlesearch import search as google_search_tool

    def google_web_search_adapter(query: str) -> str:
        """
        Performs a search and returns the top 5 results as a newline-separated string.
        """
        print(f"Performing web search for: '{query}'")
        try:
            results_iterator = google_search_tool(query, num_results=5)
            return "\n".join(list(results_iterator))
        except Exception as e:
            print(f"Web search failed: {e}")
            return ""

    di.google_web_search = google_web_search_adapter
    print(
        "Successfully imported and configured the googlesearch-python tool for the web server."
    )
except ImportError:
    print(
        "Could not import googlesearch for the web server. Web search will be disabled."
    )

    def placeholder_search(query: str = ""):
        return ""

    di.google_web_search = placeholder_search


# REMOVED: Dangerous endpoint that saved API keys to plaintext file
# API keys should ONLY be set via environment variables
# Set GEMINI_API_KEY environment variable instead
#
# @app.route("/save_gemini_api_key", methods=["POST"])
# def save_gemini_api_key():
#     # SECURITY ISSUE: Stored API keys in plaintext file
#     pass


@app.route("/api/models")
@limiter.limit("30 per minute")
def get_models():
    """Get available models for a provider without mutating global config.

    FIXED: Thread-safety issue - no longer modifies global config at runtime.
    """
    provider = request.args.get("provider")
    client_type = request.args.get("client_type")

    if not provider or not client_type:
        return jsonify({"error": "provider and client_type required"}), 400

    # Create a temporary LLM service with the requested provider
    # This avoids mutating global state
    from .llm_providers.gemini import GeminiProvider
    from .llm_providers.ollama import OllamaProvider
    import os

    models = []
    try:
        if provider == "gemini":
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key:
                client = GeminiProvider(api_key=api_key, timeout=config.LLM_TIMEOUT)
                models = client.get_available_models()
        elif provider == "ollama":
            # Use config values for URL
            cfg = config.get_config()
            url = (
                cfg.scanner_ollama_url
                if client_type == "scanner"
                else cfg.patcher_ollama_url
            )
            client = OllamaProvider(host_url=url, timeout=config.LLM_TIMEOUT)
            models = client.get_available_models()
        elif provider == "llama.cpp":
            # llama.cpp doesn't have listable models
            models = []
    except Exception as e:
        print(f"Error getting models for provider {provider}: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify(models)


@app.route("/config")
def config_page():
    """Display configuration page with current settings."""
    llm_service = LLMService()
    scanner_models = llm_service.get_available_models("scanner")
    patcher_models = llm_service.get_available_models("patcher")
    cfg = config.get_config()
    return render_template(
        "config.html",
        config=cfg,
        scanner_models=scanner_models,
        patcher_models=patcher_models,
    )


@app.route("/save_llm_settings", methods=["POST"])
@limiter.limit("10 per hour")
def save_llm_settings():
    """Save LLM settings to JSON config file.

    FIXED: Code injection vulnerability - now saves to JSON instead of writing Python code.
    All user input is validated through Pydantic schema.
    """
    from .config_schema import VRaptorConfig, save_config
    from pydantic import ValidationError

    try:
        # Load current config
        cfg = config.get_config()

        # Update with form data - Pydantic validates all inputs
        updated_data = {
            "scanner_llm_provider": request.form.get("scanner_llm_provider"),
            "scanner_llama_cpp_model_path": request.form.get(
                "scanner_llama_cpp_model_path"
            ),
            "scanner_ollama_model": request.form.get("scanner_ollama_model"),
            "scanner_ollama_url": request.form.get("scanner_ollama_url"),
            "scanner_gemini_model": request.form.get("scanner_gemini_model"),
            "patcher_llm_provider": request.form.get("patcher_llm_provider"),
            "patcher_llama_cpp_model_path": request.form.get(
                "patcher_llama_cpp_model_path"
            ),
            "patcher_ollama_model": request.form.get("patcher_ollama_model"),
            "patcher_ollama_url": request.form.get("patcher_ollama_url"),
            "patcher_gemini_model": request.form.get("patcher_gemini_model"),
            "llm_timeout": int(request.form.get("llm_timeout", 60)),
            "database_url": cfg.database_url,  # Preserve database URL
            "gitleaks_path": request.form.get("gitleaks_path"),
            "semgrep_path": request.form.get("semgrep_path"),
            "bandit_path": request.form.get("bandit_path"),
        }

        # Validate and create new config
        new_config = VRaptorConfig(**updated_data)

        # Save to config.json
        save_config(new_config)

        # Reload config module
        config.reload_config()

        flash("Configuration saved successfully. Changes are now active.", "success")
    except ValidationError as e:
        # Pydantic validation errors
        flash(f"Configuration validation failed: {e}", "error")
    except Exception as e:
        flash(f"Error saving configuration: {e}", "error")

    return redirect(url_for("config_page"))


@app.route("/failed_jobs")
def failed_jobs():
    registry = FailedJobRegistry(queue=q)
    failed_jobs = []
    for job_id in registry.get_job_ids():
        job = q.fetch_job(job_id)
        if job:
            failed_jobs.append(
                {
                    "id": job.id,
                    "func_name": job.func_name,
                    "args": job.args,
                    "kwargs": job.kwargs,
                    "exc_info": job.exc_info,
                }
            )
    return render_template("failed_jobs.html", failed_jobs=failed_jobs)


@app.route("/reports")
def reports():
    session = g.db_session

    # Subquery to find the latest scan_id for each repository
    latest_scan_ids_subquery = (
        session.query(Scan.repository_id, func.max(Scan.id).label("latest_scan_id"))
        .group_by(Scan.repository_id)
        .subquery()
    )

    top_vulnerabilities = (
        session.query(Finding.description, func.count(Finding.id).label("count"))
        .join(Scan, Finding.scan_id == Scan.id)
        .join(
            latest_scan_ids_subquery,
            Scan.repository_id == latest_scan_ids_subquery.c.repository_id,
        )
        .filter(Scan.id == latest_scan_ids_subquery.c.latest_scan_id)
        .group_by(Finding.description)
        .order_by(func.count(Finding.id).desc())
        .limit(5)
        .all()
    )

    top_repos = (
        session.query(
            Repository.id, Repository.name, func.count(Finding.id).label("count")
        )
        .join(Scan, Repository.id == Scan.repository_id)
        .join(Finding, Finding.scan_id == Scan.id)
        .join(
            latest_scan_ids_subquery,
            Scan.repository_id == latest_scan_ids_subquery.c.repository_id,
        )
        .filter(Scan.id == latest_scan_ids_subquery.c.latest_scan_id)
        .group_by(Repository.id, Repository.name)
        .order_by(func.count(Finding.id).desc())
        .limit(5)
        .all()
    )

    return render_template(
        "reports.html", top_vulnerabilities=top_vulnerabilities, top_repos=top_repos
    )


@app.route("/failed_jobs/<job_id>")
def failed_job(job_id):
    job = q.fetch_job(job_id)
    return render_template("failed_job.html", job=job)


@app.route("/dashboard")
def dashboard():
    session = g.db_session
    orchestrator = Orchestrator(None, session, di.google_web_search)
    metrics = orchestrator.get_dashboard_metrics()
    recent_scans = session.query(Scan).order_by(Scan.created_at.desc()).limit(5).all()
    findings_by_severity = orchestrator.get_findings_by_severity()
    findings_by_repo = orchestrator.get_findings_by_repo()
    findings_by_repo_json = [[repo, count] for repo, count in findings_by_repo]

    avg_quality_metrics = orchestrator.dashboard.get_average_quality_metrics_by_repo()
    quality_metrics_json = {
        "labels": [row.name for row in avg_quality_metrics],
        "avg_complexity": [
            round(row.avg_complexity or 0, 2) for row in avg_quality_metrics
        ],
        "avg_lloc": [round(row.avg_lloc or 0, 2) for row in avg_quality_metrics],
    }

    return render_template(
        "dashboard.html",
        metrics=metrics,
        recent_scans=recent_scans,
        findings_by_severity=findings_by_severity,
        findings_by_repo=findings_by_repo_json,
        quality_metrics=quality_metrics_json,
    )


@app.route("/")
def index():
    session = g.db_session
    repos = session.query(Repository).all()
    return render_template("index.html", repos=repos)


@app.route("/add_repo", methods=["POST"])
@limiter.limit("20 per hour")
def add_repo():
    """Add a repository with input validation.

    FIXED: Added input validation to prevent injection attacks.
    """
    # Validate input
    success, error_msg, validated_data = validate_input(
        RepositoryUrlInput, {"repo_url": request.form.get("repo_url", "")}
    )

    if not success:
        flash(f"Invalid input: {error_msg}", "error")
        return redirect(url_for("index"))

    repo_url = validated_data["repo_url"]
    vcs_service = VCSService(git_provider="github", token="")
    base_url, detected_branch = vcs_service.parse_and_validate_repo_url(repo_url)

    if not base_url:
        flash(
            f"Error: Could not find a valid repository at '{repo_url}'. Please check the URL.",
            "error",
        )
        return redirect(url_for("index"))

    branches = vcs_service.get_branches(base_url)
    if not branches:
        flash(
            f"Error: Found repository '{base_url}' but could not fetch its branches.",
            "error",
        )
        return redirect(url_for("index"))

    return render_template(
        "select_branch.html",
        repo_url=base_url,
        branches=branches,
        selected_branch=detected_branch,
    )


@app.route("/confirm_add_repo", methods=["POST"])
def confirm_add_repo():
    """Confirm adding repository with input validation.

    FIXED: Added input validation to prevent injection attacks.
    """
    # Validate input
    success, error_msg, validated_data = validate_input(
        RepositoryConfirmInput,
        {
            "repo_url": request.form.get("repo_url", ""),
            "branch": request.form.get("branch", ""),
        },
    )

    if not success:
        flash(f"Invalid input: {error_msg}", "error")
        return redirect(url_for("index"))

    repo_url = validated_data["repo_url"]
    selected_branch = validated_data["branch"]

    session = g.db_session
    if session.query(Repository).filter_by(url=repo_url).first():
        flash(f"Repository '{repo_url}' is already being monitored.", "info")
        return redirect(url_for("index"))

    repo_name = repo_url.split("/")[-1].replace(".git", "")
    new_repo = Repository(name=repo_name, url=repo_url, primary_branch=selected_branch)
    session.add(new_repo)
    session.commit()
    flash(
        f"Successfully added repository '{repo_name}' (monitoring branch '{selected_branch}').",
        "success",
    )
    return redirect(url_for("index"))


@app.route("/repository/<int:repo_id>/periodic_scan", methods=["POST"])
def periodic_scan_config(repo_id):
    """Configure periodic scans with input validation.

    FIXED: Added input validation for scan intervals.
    """
    # Validate input
    success, error_msg, validated_data = validate_input(
        PeriodicScanInput,
        {
            "periodic_scan_enabled": "periodic_scan_enabled" in request.form,
            "periodic_scan_interval": request.form.get(
                "periodic_scan_interval", "86400"
            ),
        },
    )

    if not success:
        flash(f"Invalid input: {error_msg}", "error")
        return redirect(url_for("repository", repo_id=repo_id))

    session = g.db_session
    repo = session.query(Repository).get(repo_id)
    if repo:
        repo.periodic_scan_enabled = validated_data["periodic_scan_enabled"]
        repo.periodic_scan_interval = validated_data["periodic_scan_interval"]
        session.commit()
        flash("Periodic scan settings updated.", "success")
    else:
        flash("Repository not found.", "error")

    return redirect(url_for("repository", repo_id=repo_id))


@app.route("/remove_repo/<int:repo_id>", methods=["POST"])
def remove_repo(repo_id):
    session = g.db_session
    repo = session.query(Repository).get(repo_id)
    if repo:
        session.delete(repo)
        session.commit()
        return redirect(url_for("index"))


@app.route("/repository/<int:repo_id>")
def repository(repo_id):
    session = g.db_session
    repo = (
        session.query(Repository)
        .options(selectinload(Repository.scans))
        .filter_by(id=repo_id)
        .one()
    )

    if not repo:
        flash(f"Repository with ID {repo_id} not found.", "error")
        return redirect(url_for("index"))
    scans_as_list = list(repo.scans)
    print(f"--- DEBUG: Found repository: {repo.name} ---")
    print(f"--- DEBUG: Scans object from relation: {repo.scans} ---")
    print(f"--- DEBUG: Number of scans found: {len(repo.scans)} ---")
    return render_template("repository.html", repo=repo, scans_as_list=scans_as_list)


@app.route("/repository/<int:repo_id>/quality")
def quality(repo_id):
    session = g.db_session
    repo = session.query(Repository).get(repo_id)
    scan = (
        session.query(Scan)
        .filter_by(repository_id=repo_id, scan_type="quality")
        .order_by(Scan.created_at.desc())
        .first()
    )

    sort_by = request.args.get("sort_by", "file_path")
    sort_order = request.args.get("sort_order", "asc")

    if scan:
        metrics_query = session.query(QualityMetric).filter_by(scan_id=scan.id)

        sort_column = getattr(QualityMetric, sort_by, QualityMetric.file_path)
        if sort_order == "desc":
            metrics_query = metrics_query.order_by(sort_column.desc())
        else:
            metrics_query = metrics_query.order_by(sort_column.asc())

        metrics = metrics_query.all()
    else:
        metrics = []

    return render_template(
        "quality.html",
        repo=repo,
        metrics=metrics,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@app.route("/api/scans")
def api_scans():
    session = g.db_session
    scans = session.query(Scan).order_by(Scan.created_at.desc()).all()
    scans_data = []
    for scan in scans:
        job = q.fetch_job(str(scan.id))
        scans_data.append(
            {
                "id": scan.id,
                "status": scan.status.value,
                "status_message": scan.status_message,
                "job_id": job.id if job else None,
            }
        )
    return jsonify(scans_data)


@app.route("/scans")
def scans():
    session = g.db_session
    scans = session.query(Scan).order_by(Scan.created_at.desc()).all()
    return render_template("scans.html", scans=scans)


@app.route("/findings")
def findings():
    session = g.db_session
    findings = session.query(Finding).order_by(Finding.id.desc()).all()

    for finding in findings:
        description_no_paren = finding.description.replace("(", "").replace(")", "")
        url_match = re.search(r"https?://\S+", description_no_paren)

        if url_match:
            url = url_match.group(0)
            text = finding.description.replace(f"({url})", "").strip()
            finding.description_text = text
            finding.description_url = url

            # Extract rule ID
            if "semgrep.dev" in url:
                finding.rule_id = url.split("/")[-1]
            elif "bandit.readthedocs.io" in url:
                finding.rule_id = url.split("/")[-1].replace(".html", "")
            else:
                finding.rule_id = "doc"
        else:
            finding.description_text = finding.description
            finding.description_url = None
            finding.rule_id = None

    return render_template("findings.html", findings=findings)


@app.route("/findings/by_description")
def findings_by_description():
    description = request.args.get("description")
    session = g.db_session
    findings = session.query(Finding).filter_by(description=description).all()
    return render_template(
        "findings.html", findings=findings, title=f"Findings for '{description}'"
    )


@app.route("/run_scan/<int:repo_id>", methods=["POST"])
@limiter.limit("10 per hour")
def run_scan(repo_id):
    """Run a deep scan with input validation.

    FIXED: Added validation for repo_id and scan options.
    """
    app.logger.info(f"--- run_scan called for repo_id: {repo_id} ---")

    # Validate inputs
    success, error_msg, validated_data = validate_input(
        ScanConfigInput,
        {
            "repo_id": repo_id,
            "auto_patch": "auto_patch" in request.form,
        },
    )

    if not success:
        flash(f"Invalid input: {error_msg}", "error")
        return redirect(url_for("index"))

    auto_patch = validated_data["auto_patch"]
    include_tests = "include_tests" in request.form

    session = g.db_session
    repo = session.query(Repository).get(repo_id)
    if repo:
        scan = Scan(
            repository_id=repo.id,
            scan_type="deep",
            status="queued",
            auto_patch_enabled=auto_patch,
        )
        session.add(scan)
        session.commit()
        app.logger.info(f"--- Created scan with id: {scan.id} ---")
        job = q.enqueue(
            "src.worker.run_deep_scan_job",
            repo.url,
            scan.id,
            auto_patch=auto_patch,
            include_tests=include_tests,
        )
        scan.job_id = job.id
        session.commit()
        flash(f"Deep scan initiated for '{repo.name}'.", "info")
    else:
        flash("Repository not found.", "error")

    return redirect(url_for("repository", repo_id=repo_id))


@app.route("/scan_new_commits/<int:repo_id>", methods=["POST"])
@limiter.limit("20 per hour")
def scan_new_commits(repo_id):
    session = g.db_session
    repo = session.query(Repository).get(repo_id)
    if repo and repo.needs_scan:
        job = q.enqueue(
            "src.worker.run_analysis_job",
            repo.url,
            repo.last_commit_hash,
            repo.id,
            auto_patch=False,
        )
        scan = Scan(
            repository_id=repo.id,
            scan_type="commit",
            status="queued",
            job_id=job.id,
            triggering_commit_hash=repo.last_commit_hash,
        )
        session.add(scan)
        repo.needs_scan = False
        session.commit()
        flash(f"Scan for new commits initiated for '{repo.name}'.", "info")
    return redirect(url_for("index"))


@app.route("/run_quality_scan/<int:repo_id>", methods=["POST"])
@limiter.limit("10 per hour")
def run_quality_scan(repo_id):
    session = g.db_session
    repo = session.query(Repository).get(repo_id)
    if repo:
        job = q.enqueue("src.worker.run_quality_scan_job", repo_id)
        scan = Scan(
            repository_id=repo.id, scan_type="quality", status="queued", job_id=job.id
        )
        session.add(scan)
        session.commit()
        flash("Code quality scan initiated for repository.", "info")
    return redirect(url_for("repository", repo_id=repo_id))


@app.route("/link_cves/<int:repo_id>", methods=["POST"])
def link_cves(repo_id):
    session = g.db_session
    repo = session.query(Repository).get(repo_id)
    if repo:
        scan = Scan(repository_id=repo.id, scan_type="cve-linking", status="queued")
        session.add(scan)
        session.commit()
        job = q.enqueue("src.worker.link_cves_to_findings_job", repo_id, scan.id)
        scan.job_id = job.id
        session.commit()
        flash("CVE linking initiated for repository.", "info")
    return redirect(url_for("repository", repo_id=repo_id))


@app.route("/rerun_scan/<int:scan_id>", methods=["POST"])
def rerun_scan(scan_id):
    session = g.db_session
    scan = session.query(Scan).get(scan_id)
    if scan:
        if scan.scan_type == "commit":
            job = q.enqueue(
                "src.worker.run_analysis_job",
                scan.repository.url,
                scan.triggering_commit_hash,
                scan.repository.id,
                auto_patch=scan.auto_patch_enabled,
            )
        else:
            job = q.enqueue(
                "src.worker.run_deep_scan_job",
                scan.repository.url,
                auto_patch=scan.auto_patch_enabled,
            )
        scan.job_id = job.id
        scan.status = "queued"
        session.commit()
        flash(f"Rerunning scan {scan.id} for '{scan.repository.name}'.", "info")
    return redirect(url_for("repository", repo_id=scan.repository.id))


@app.route("/generate_patch/<int:finding_id>", methods=["POST"])
@limiter.limit("30 per hour")
def generate_patch(finding_id):
    session = g.db_session
    vcs_service = VCSService(git_provider="github", token="")
    orchestrator = Orchestrator(vcs_service, session, di.google_web_search)
    orchestrator.rewrite_remediation(finding_id)
    flash(f"Patch generation initiated for Finding #{finding_id}.", "info")
    return redirect(url_for("finding", finding_id=finding_id))


# ...
@app.route("/stop_scan/<int:scan_id>", methods=["POST"])
def stop_scan(scan_id):
    session = g.db_session
    scan = session.query(Scan).get(scan_id)
    if scan and scan.job_id:
        job = q.fetch_job(scan.job_id)
        if job:
            job.cancel()
            scan.status = ScanStatus.FAILED
            session.commit()
            flash(f"Scan {scan_id} stopped.", "success")
        else:
            flash(f"Job {scan.job_id} not found in queue.", "error")
    else:
        flash(f"Scan {scan_id} not found or has no job ID.", "error")
    return redirect(url_for("scans"))


@app.route("/delete_scan/<int:scan_id>", methods=["POST", "DELETE"])
def delete_scan(scan_id):
    session = g.db_session
    scan = session.query(Scan).get(scan_id)
    if scan:
        session.delete(scan)
        session.commit()
        flash(f"Scan {scan_id} deleted.", "success")
    else:
        flash(f"Scan {scan_id} not found.", "error")
    return redirect(url_for("scans"))


@app.route("/mark_scan_failed/<int:scan_id>", methods=["POST"])
def mark_scan_failed(scan_id):
    session = g.db_session
    scan = session.query(Scan).get(scan_id)
    if scan:
        scan.status = ScanStatus.FAILED
        session.commit()
        flash(f"Scan {scan_id} marked as failed.", "success")
    else:
        flash(f"Scan {scan_id} not found.", "error")
    return redirect(url_for("scans"))


@app.route("/interpret_quality_metrics/<int:metric_id>")
def interpret_quality_metrics(metric_id):
    session = g.db_session
    metric = session.query(QualityMetric).get(metric_id)
    if not metric:
        flash("Metric not found.", "error")
        return redirect(url_for("quality", repo_id=metric.scan.repository.id))

    if metric.interpretation:
        return redirect(
            url_for(
                "quality_interpretation", interpretation_id=metric.interpretation.id
            )
        )

    orchestrator = Orchestrator(None, session, None)
    interpretation_text = orchestrator.llm_service.interpret_quality_metrics(metric)

    new_interpretation = QualityInterpretation(
        quality_metric_id=metric.id, interpretation=interpretation_text
    )
    session.add(new_interpretation)
    session.commit()

    return redirect(
        url_for("quality_interpretation", interpretation_id=new_interpretation.id)
    )


@app.route("/quality_interpretation/<int:interpretation_id>")
def quality_interpretation(interpretation_id):
    session = g.db_session
    interpretation = session.query(QualityInterpretation).get(interpretation_id)
    metric = interpretation.quality_metric
    chat_history = (
        session.query(ChatMessage)
        .filter_by(quality_interpretation_id=interpretation_id)
        .order_by(ChatMessage.created_at)
        .all()
    )
    return render_template(
        "quality_interpretation.html",
        interpretation=interpretation,
        metric=metric,
        chat_history=chat_history,
    )


@app.route(
    "/chat_with_quality_interpretation/<int:interpretation_id>", methods=["POST"]
)
def chat_with_quality_interpretation(interpretation_id):
    data = request.get_json()
    message = data.get("message")
    if not message:
        return jsonify({"error": "Message is required"}), 400

    session = g.db_session
    vcs_service = VCSService(git_provider="github", token="")
    orchestrator = Orchestrator(vcs_service, session, None)
    response = orchestrator.chat_with_quality_interpretation(interpretation_id, message)
    return jsonify({"response": response})


@app.route("/reset_chat/<string:chat_type>/<int:chat_id>", methods=["POST"])
def reset_chat(chat_type, chat_id):
    session = g.db_session
    if chat_type == "finding":
        messages = session.query(ChatMessage).filter_by(finding_id=chat_id).all()
    elif chat_type == "quality":
        messages = (
            session.query(ChatMessage)
            .filter_by(quality_interpretation_id=chat_id)
            .all()
        )
    else:
        return jsonify({"status": "error", "message": "Invalid chat type"}), 400

    for message in messages:
        session.delete(message)
    session.commit()

    return jsonify({"status": "success", "message": "Chat history has been reset."})


@app.route("/scan/<int:scan_id>")
def scan(scan_id):
    session = g.db_session
    scan = session.query(Scan).get(scan_id)
    app.logger.info(f"Scan type for scan {scan_id} is {scan.scan_type}")

    if scan.scan_type == "quality":
        sort_by = request.args.get("sort_by", "file_path")
        sort_order = request.args.get("sort_order", "asc")

        metrics = sorted(
            scan.quality_metrics,
            key=lambda m: getattr(m, sort_by),
            reverse=sort_order == "desc",
        )

        return render_template(
            "quality.html",
            repo=scan.repository,
            metrics=metrics,
            sort_by=sort_by,
            sort_order=sort_order,
            scan_id=scan_id,
        )
    else:
        severity_filter = request.args.get("severity")
        scanner_filter = request.args.get("scanner")
        sort_by = request.args.get("sort_by", "severity")
        sort_order = request.args.get("sort_order", "desc")
        keyword = request.args.get("keyword")

        findings_query = session.query(Finding).filter(Finding.scan_id == scan_id)

        if severity_filter:
            findings_query = findings_query.filter(Finding.severity == severity_filter)

        if scanner_filter:
            findings_query = findings_query.filter(
                Finding.description.like(f"{scanner_filter}:%")
            )

        if keyword:
            findings_query = findings_query.filter(
                Finding.description.ilike(f"%{keyword}%")
            )

        if sort_by == "severity":
            severity_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]
            # Create a CASE statement for custom sorting
            case_statement = case(
                *[
                    (Finding.severity == severity, index)
                    for index, severity in enumerate(severity_order)
                ],
                else_=len(severity_order),  # Unknown severities go last
            )
            if sort_order == "desc":
                findings_query = findings_query.order_by(case_statement.desc())
            else:
                findings_query = findings_query.order_by(case_statement.asc())
        elif sort_by == "file":
            if sort_order == "desc":
                findings_query = findings_query.order_by(Finding.file_path.desc())
            else:
                findings_query = findings_query.order_by(Finding.file_path.asc())

        findings = findings_query.all()

        return render_template(
            "scan.html",
            scan=scan,
            findings=findings,
            severity_filter=severity_filter,
            scanner_filter=scanner_filter,
            sort_by=sort_by,
            sort_order=sort_order,
            keyword=keyword,
        )


@app.route("/finding/<int:finding_id>")
def finding(finding_id):
    session = g.db_session
    finding = session.query(Finding).get(finding_id)
    chat_history = (
        session.query(ChatMessage)
        .filter_by(finding_id=finding_id)
        .order_by(ChatMessage.created_at)
        .all()
    )

    if finding:
        description_no_paren = finding.description.replace("(", "").replace(")", "")
        url_match = re.search(r"https?://\S+", description_no_paren)

        if url_match:
            url = url_match.group(0)
            text = finding.description.replace(f"({url})", "").strip()
            finding.description_text = text
            finding.description_url = url

            # Extract rule ID
            if "semgrep.dev" in url:
                finding.rule_id = url.split("/")[-1]
            elif "bandit.readthedocs.io" in url:
                finding.rule_id = url.split("/")[-1].replace(".html", "")
            else:
                finding.rule_id = "doc"
        else:
            finding.description_text = finding.description
            finding.description_url = None
            finding.rule_id = None

    return render_template("finding.html", finding=finding, chat_history=chat_history)


@app.route("/finding/<int:finding_id>/search_cve", methods=["POST"])
def search_cve(finding_id):
    session = g.db_session
    finding = session.query(Finding).get(finding_id)
    if finding:
        orchestrator = Orchestrator(None, session, di.google_web_search)
        orchestrator.search_cve_for_finding(finding)
        flash("CVE search initiated. The finding will be updated shortly.", "info")
    return redirect(url_for("finding", finding_id=finding_id))


@app.route("/recheck_finding/<int:finding_id>", methods=["POST"])
def recheck_finding(finding_id):
    session = g.db_session
    vcs_service = VCSService(git_provider="github", token="")
    orchestrator = Orchestrator(vcs_service, session, di.google_web_search)
    orchestrator.recheck_finding(finding_id)
    return redirect(url_for("finding", finding_id=finding_id))


@app.route("/rewrite_remediation/<int:finding_id>", methods=["POST"])
@limiter.limit("30 per hour")
def rewrite_remediation(finding_id):
    session = g.db_session
    vcs_service = VCSService(git_provider="github", token="")
    orchestrator = Orchestrator(vcs_service, session, di.google_web_search)
    orchestrator.rewrite_remediation(finding_id)
    return redirect(url_for("finding", finding_id=finding_id))


@app.route("/update_patch/<int:finding_id>", methods=["POST"])
def update_patch(finding_id):
    patch_diff = request.form["patch_diff"]
    session = g.db_session
    patch = session.query(Patch).filter_by(finding_id=finding_id).first()
    if patch:
        patch.generated_patch_diff = patch_diff
        session.commit()
    return redirect(url_for("finding", finding_id=finding_id))


@app.route("/chat/<int:finding_id>", methods=["POST"])
@limiter.limit("60 per hour")
def chat(finding_id):
    message = request.json["message"]
    session = g.db_session
    vcs_service = VCSService(git_provider="github", token="")
    orchestrator = Orchestrator(vcs_service, session, di.google_web_search)
    response = orchestrator.chat_with_finding(finding_id, message)
    return {"response": response}


@app.route("/ci/scan", methods=["POST"])
@csrf.exempt
@limiter.limit("100 per hour")
def ci_scan():
    """CI/CD webhook scan endpoint with input validation.

    FIXED: Added validation for repository URLs and commit hashes.
    CSRF exempt: This is a webhook endpoint that receives requests from external CI/CD systems.
    """
    # Validate input
    success, error_msg, validated_data = validate_input(
        CIScanInput,
        {
            "repo_url": request.json.get("repo_url", "") if request.json else "",
            "commit_hash": request.json.get("commit_hash") if request.json else None,
        },
    )

    if not success:
        return jsonify({"status": "failure", "message": error_msg}), 400

    repo_url = validated_data["repo_url"]
    commit_hash = validated_data.get("commit_hash")

    session = g.db_session
    vcs_service = VCSService(git_provider="github", token="")

    repository = session.query(Repository).filter_by(url=repo_url).first()
    if not repository:
        primary_branch = vcs_service.get_primary_branch(repo_url)
        if not primary_branch:
            return jsonify(
                {
                    "status": "failure",
                    "message": f"Could not determine primary branch for {repo_url}.",
                }
            ), 400
        repository = Repository(
            name=repo_url.split("/")[-1], url=repo_url, primary_branch=primary_branch
        )
        session.add(repository)
        session.commit()

    if not commit_hash:
        commit_hash = vcs_service.get_latest_commit_hash(
            repo_url, repository.primary_branch
        )
        if not commit_hash:
            return jsonify(
                {
                    "status": "failure",
                    "message": f"Could not get latest commit hash for {repo_url}.",
                }
            ), 400

    job = q.enqueue(
        "src.worker.run_analysis_job",
        repo_url,
        commit_hash,
        repository.id,
        auto_patch=False,
    )
    scan = Scan(
        repository_id=repository.id,
        scan_type="commit",
        status="queued",
        job_id=job.id,
        triggering_commit_hash=commit_hash,
    )
    session.add(scan)
    session.commit()

    return jsonify(
        {
            "status": "success",
            "message": f"Scan initiated for {repo_url} at commit {commit_hash}.",
        }
    )


def synchronize_scan_statuses(session):  # <--- ACCEPT SESSION AS AN ARGUMENT
    """Synchronizes the scan statuses with the RQ queue."""
    # No longer creates or closes its own session. It uses the one passed to it.
    with app.app_context():  # Keep the app context for logging or other extensions
        scans = (
            session.query(Scan)
            .filter(Scan.status.in_([ScanStatus.RUNNING, ScanStatus.QUEUED]))
            .all()
        )
        app.logger.info(f"Found {len(scans)} running or queued scans to synchronize.")
        for scan in scans:
            if scan.job_id:
                job = q.fetch_job(scan.job_id)
                app.logger.info(
                    f"Checking job {scan.job_id} for scan {scan.id}. Job status: {job.get_status() if job else 'not found'}"
                )
                if job is None or job.get_status() == "failed":
                    app.logger.info(f"Updating scan {scan.id} to FAILED.")
                    scan.status = ScanStatus.FAILED
                    session.commit()
            else:
                app.logger.info(f"Scan {scan.id} has no job ID, marking as FAILED.")
                scan.status = ScanStatus.FAILED
                session.commit()
        app.logger.info("Synchronization complete.")


def periodic_sync():
    """Periodically synchronizes the scan statuses."""
    import time
    import logging

    logging.basicConfig(level=logging.INFO)

    while True:
        session = None  # Define session outside the try block
        try:
            logging.info("Periodic Sync: Creating new DB session...")
            # Create a new session for this run
            session = get_session()()
            # Pass the session to the sync function
            synchronize_scan_statuses(session)
        except Exception:
            logging.error(
                "An error occurred in the periodic sync process.", exc_info=True
            )
        finally:
            # This is critical: always close the session to prevent leaks
            if session:
                session.close()
                logging.info("Periodic Sync: DB session closed.")
        time.sleep(10)


@app.before_request
def before_request():
    """
    Get a session from the pool and store it in the application context.
    """
    g.db_session = get_session()()


@app.teardown_appcontext
def shutdown_session(exception=None):
    """
    Remove the database session at the end of the request or when the app shuts down.
    """
    db_session = g.pop("db_session", None)
    if db_session is not None:
        db_session.close()
