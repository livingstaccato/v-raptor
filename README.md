# V-Raptor

V-Raptor is an AI agent for automated code analysis, bug detection, and remediation.

## Features

- **Automated Code Analysis:** Analyzes code for security vulnerabilities, bugs, and code quality problems.
- **Automated Remediation:** Generates patches for detected vulnerabilities and bugs.
- **Manual and Deep Scans:** Perform deep scans of repositories to find hidden vulnerabilities and secrets, or trigger scans manually from the web UI.
- **Dependency and Configuration Scanning:** Scans dependencies for known vulnerabilities and configuration files for security misconfigurations.
- **Webhook Support:** Continuously analyze code by listening for webhook events from your Git provider.
- **Web UI:** A simple web UI to browse scan results, manage repositories, and configure the application.

## Screenshots

![Scan Results](docs/screenshots/scan_results.png)

## Getting Started

### Prerequisites

- Python 3.10 or later
- Docker
- Go
- Redis

### Environment Variables

V-Raptor requires the following environment variables to be set:

```bash
# Required for Gemini LLM provider
export GEMINI_API_KEY='your-gemini-api-key-here'

# Required for creating pull requests with patches
export GITHUB_TOKEN='your-github-token-here'

# Optional - Redis configuration
export REDIS_HOST='localhost'  # Default: localhost
export REDIS_PORT='6379'        # Default: 6379

# Optional - Logging configuration
export LOG_LEVEL='INFO'         # Default: INFO (DEBUG, INFO, WARNING, ERROR, CRITICAL)
export LOG_FORMAT='console'     # Default: console (console or json)
export LOG_FILE='/var/log/v-raptor.log'  # Optional: file path for logs
```

**Security Note:** API keys are ONLY loaded from environment variables. They are never stored in files or the database. See [SECURITY_FIXES.md](SECURITY_FIXES.md) for details on security improvements.

**Logging Note:** V-Raptor uses structured logging with support for both human-readable console output and JSON formatting for production. Use `LOG_FORMAT=json` for production deployments to enable log aggregation and analysis.

### Installation

1. Clone the repository:

```
git clone https://github.com/your-username/v-raptor.git
```

2. Install the dependencies:

```bash
./run.sh
```

3. Initialize the database:

```bash
./run.sh --init-db
```

4. Build the Docker sandbox image:

```bash
docker build -t v-raptor-sandbox:latest .
```

This image is required for secure vulnerability testing and patch validation. The application will fail to start if this image is not present.

### Running with Docker Compose

V-Raptor can be run with Docker Compose, which will build the Docker image and start the web server, worker, and Redis.

1. Start the application:

```
docker-compose up --build
```

This will build the Docker image, start the containers, and show the logs. To run in the background, use `docker-compose up -d --build`.

2. Open your browser and go to `http://localhost:5000`.

## Usage

V-Raptor can be used in several ways:

### Web UI

The easiest way to use V-Raptor is through the web UI.

1. Start the web server:

```
./run.sh start-web
```

2. Open your browser and go to `http://localhost:5000`.

From the web UI, you can:
- Add and remove repositories.
- Run and re-run scans.
- View scan results and findings.
- Configure the application.

### Command Line

You can also run scans from the command line.

To run a deep scan of a repository:

```
./run.sh --scan-url <repository-url>
```

To scan a specific commit:

```
./run.sh --scan-url <repository-url> --scan-commit <commit-hash>
```

To scan a local repository:

```
./run.sh --scan-local /path/to/your/repo
```

You can also output the findings in JSON format, which is useful for scripting and integrations:

```
./run.sh --scan-local /path/to/your/repo --output-json
```

## Configuration

V-Raptor uses a hybrid configuration approach:

### Environment Variables (Required for Secrets)

**API keys and tokens must be set via environment variables** for security:
- `GEMINI_API_KEY` - Required for Gemini LLM provider
- `GITHUB_TOKEN` - Required for creating pull requests

### Configuration File (config.json)

Application settings are stored in `config.json` at the project root. You can modify this file directly or use the web UI configuration page to update:
- LLM provider selection (Gemini, Ollama, llama.cpp)
- Model names and endpoints
- Timeout values
- Database and tool paths

### Web UI Configuration

Go to the "Configuration" page in the web UI to:
- Select LLM providers
- Configure model settings
- Adjust timeout values
- Test LLM connectivity

**Note:** The web UI cannot be used to set API keys for security reasons. All secrets must be set via environment variables.

## Advanced Usage

For more advanced usage, including server mode, git hooks, and webhooks, see the [Advanced Usage](docs/advanced_usage.md) documentation.
