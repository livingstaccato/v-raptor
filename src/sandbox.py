import docker
import io
import tarfile


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
                print(f"✓ Sandbox image '{self.image_name}' found and ready.")
            except docker.errors.ImageNotFound:
                raise RuntimeError(
                    f"Docker image '{self.image_name}' not found.\n"
                    f"Please build it with:\n"
                    f"  docker build -t {self.image_name} .\n"
                    f"Or use the existing Dockerfile in the project root."
                )
        except docker.errors.DockerException as e:
            raise RuntimeError(f"Docker is not running or misconfigured: {e}")

    def create_sandbox(self):
        """Creates a new sandbox from the pre-built image."""
        try:
            print(f"Creating sandbox from image: {self.image_name}...")
            # Run container with a command that keeps it alive
            container = self.client.containers.run(
                self.image_name, command="tail -f /dev/null", detach=True
            )
            print(f"Sandbox created with ID: {container.id[:12]}")
            return container.id
        except docker.errors.ImageNotFound:
            print(f"Error: The Docker image '{self.image_name}' was not found.")
            print("Please build the sandbox image using the provided Dockerfile.")
            return None
        except Exception as e:
            print(f"Error creating sandbox: {e}")
            return None

    def execute_in_sandbox(self, container_id, command):
        """Executes a generic command in the sandbox."""
        try:
            container = self.client.containers.get(container_id)
            exit_code, output = container.exec_run(command)
            return output.decode("utf-8")
        except Exception as e:
            print(f"Error executing command in sandbox: {e}")
            return None

    def put_archive(self, container_id, path, data):
        """Puts a tar archive to a path in the container."""
        try:
            container = self.client.containers.get(container_id)
            container.put_archive(path, data)
        except Exception as e:
            print(f"Error putting archive in sandbox: {e}")

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
            return self.execute_in_sandbox(
                container_id, f"python3 {script_path_container}"
            )

        except Exception as e:
            print(f"Error executing Python script: {e}")
            return None

    def destroy_sandbox(self, container_id):
        """Stops and removes the sandbox container."""
        if not container_id:
            return
        try:
            print(f"Destroying sandbox: {container_id[:12]}")
            container = self.client.containers.get(container_id)
            container.stop(timeout=5)
            container.remove()
        except docker.errors.NotFound:
            pass  # Container already gone
        except Exception as e:
            print(f"Error destroying sandbox: {e}")
