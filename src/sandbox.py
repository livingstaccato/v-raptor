import docker
import io
import tarfile
from .logging_config import get_logger

logger = get_logger(__name__)


class SandboxService:
    def __init__(self):
        """Initialize sandbox service and validate Docker image exists.

        Raises:
            RuntimeError: If Docker is not running or sandbox image is not found
        """
        try:
            self.client = docker.from_env()
            # This is the name of the pre-built image. You must create this image.
            self.image_name = "v-raptor-sandbox:latest"

            # FIXED: Validate sandbox image exists on initialization
            # This fails early instead of silently failing later during scans
            try:
                self.client.images.get(self.image_name)
                logger.info(
                    "Sandbox image found and ready",
                    extra={"image_name": self.image_name},
                )
            except docker.errors.ImageNotFound:
                logger.error(
                    "Sandbox image not found", extra={"image_name": self.image_name}
                )
                raise RuntimeError(
                    f"Docker image '{self.image_name}' not found.\n"
                    f"Please build it with:\n"
                    f"  docker build -t {self.image_name} .\n"
                    f"Or use the existing Dockerfile in the project root."
                )
        except docker.errors.DockerException as e:
            logger.error(
                "Docker is not running or misconfigured",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise RuntimeError(f"Docker is not running or misconfigured: {e}")

    def create_sandbox(self):
        """Creates a new sandbox from the pre-built image."""
        try:
            logger.info("Creating sandbox", extra={"image_name": self.image_name})
            # Run container with a command that keeps it alive
            container = self.client.containers.run(
                self.image_name, command="tail -f /dev/null", detach=True
            )
            container_id_short = container.id[:12]
            logger.info(
                "Sandbox created successfully",
                extra={"container_id": container_id_short},
            )
            return container.id
        except docker.errors.ImageNotFound:
            logger.error(
                "Sandbox image not found during creation",
                extra={"image_name": self.image_name},
            )
            return None
        except Exception as e:
            logger.error(
                "Error creating sandbox", extra={"error": str(e)}, exc_info=True
            )
            return None

    def execute_in_sandbox(self, container_id, command):
        """Executes a generic command in the sandbox."""
        try:
            container = self.client.containers.get(container_id)
            exit_code, output = container.exec_run(command)
            logger.debug(
                "Command executed in sandbox",
                extra={
                    "container_id": container_id[:12],
                    "command": command,
                    "exit_code": exit_code,
                },
            )
            return output.decode("utf-8")
        except Exception as e:
            logger.error(
                "Error executing command in sandbox",
                extra={
                    "container_id": container_id[:12] if container_id else None,
                    "command": command,
                    "error": str(e),
                },
                exc_info=True,
            )
            return None

    def put_archive(self, container_id, path, data):
        """Puts a tar archive to a path in the container."""
        try:
            container = self.client.containers.get(container_id)
            container.put_archive(path, data)
            logger.debug(
                "Archive uploaded to sandbox",
                extra={"container_id": container_id[:12], "path": path},
            )
        except Exception as e:
            logger.error(
                "Error putting archive in sandbox",
                extra={
                    "container_id": container_id[:12] if container_id else None,
                    "path": path,
                    "error": str(e),
                },
                exc_info=True,
            )

    def execute_python_script(self, container_id, script_code):
        """Executes a Python script in the sandbox by copying it."""
        script_path_container = "/app/test_script.py"
        try:
            container = self.client.containers.get(container_id)

            # Create a tar archive in memory
            pw_tarstream = io.BytesIO()
            pw_tar = tarfile.TarFile(fileobj=pw_tarstream, mode="w")
            file_data = script_code.encode("utf8")
            tarinfo = tarfile.TarInfo(name="test_script.py")
            tarinfo.size = len(file_data)
            pw_tar.addfile(tarinfo, io.BytesIO(file_data))
            pw_tar.close()
            pw_tarstream.seek(0)

            # Use put_archive to copy the script file into the container
            container.put_archive("/app/", pw_tarstream)

            # Execute the script
            result = self.execute_in_sandbox(
                container_id, f"python3 {script_path_container}"
            )
            logger.debug(
                "Python script executed in sandbox",
                extra={
                    "container_id": container_id[:12],
                    "script_length": len(script_code),
                },
            )
            return result

        except Exception as e:
            logger.error(
                "Error executing Python script",
                extra={
                    "container_id": container_id[:12] if container_id else None,
                    "error": str(e),
                },
                exc_info=True,
            )
            return None

    def destroy_sandbox(self, container_id):
        """Stops and removes the sandbox container."""
        if not container_id:
            return
        try:
            logger.info("Destroying sandbox", extra={"container_id": container_id[:12]})
            container = self.client.containers.get(container_id)
            container.stop(timeout=5)
            container.remove()
            logger.debug(
                "Sandbox destroyed successfully",
                extra={"container_id": container_id[:12]},
            )
        except docker.errors.NotFound:
            logger.debug(
                "Sandbox already removed", extra={"container_id": container_id[:12]}
            )
        except Exception as e:
            logger.error(
                "Error destroying sandbox",
                extra={
                    "container_id": container_id[:12] if container_id else None,
                    "error": str(e),
                },
                exc_info=True,
            )
