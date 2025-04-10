"""
Sets up an SSH server in a Modal container.

This requires you to `pip install sshtunnel` locally.

After running this with `modal run launch_server.py`, connect to SSH with `ssh -p 9090 root@localhost`,
or from VSCode/Pycharm.

This uses simple password authentication, but you can store your own key in a modal Secret instead.
"""

import socket
import subprocess
import threading
import time

import modal

app = modal.App(
    "gsplat-trainer",
    image=modal.Image.from_dockerfile("docker/Dockerfile")
    # SSH server
    .apt_install("openssh-server")
    .run_commands(
        "mkdir -p /run/sshd", "echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config", "echo 'root: ' | chpasswd"
    )
    # VSCode
    .run_commands("curl -fsSL https://code-server.dev/install.sh | sh")
    # GCloud
    .run_commands("apt-get update && apt-get install -y curl gnupg && \
    curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    echo 'deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main' | tee -a /etc/apt/sources.list.d/google-cloud-sdk.list && \
    apt-get update && apt-get install -y \
    google-cloud-cli \
    && rm -rf /var/lib/apt/lists/*"
    )
    .add_local_file("gcs-tour-project-service-account-key.json", "/root/gcs-tour-project-service-account-key.json", copy=True)
    .run_commands(
        "gcloud auth activate-service-account --key-file=/root/gcs-tour-project-service-account-key.json",
        "gcloud config set project tour-project-442218",
        "gcloud storage ls"
    )
    .env({"GOOGLE_APPLICATION_CREDENTIALS": "/root/gcs-tour-project-service-account-key.json"})
    .run_commands("gcloud storage ls")
    # Install git
    .run_commands("apt-get install -y git")
    # Add the source code so if we need to debug we can look at it on the server
    .add_local_dir(".", "/root/")
)


LOCAL_PORT = 9090


def wait_for_port(host, port, q):
    start_time = time.monotonic()
    while True:
        try:
            with socket.create_connection(("localhost", 22), timeout=30.0):
                break
        except OSError as exc:
            time.sleep(0.01)
            if time.monotonic() - start_time >= 30.0:
                raise TimeoutError("Waited too long for port 22 to accept connections") from exc
        q.put((host, port))


@app.function(
    timeout=3600 * 24,
    gpu="T4",
    secrets=[modal.Secret.from_name("wandb-secret")],
    volumes={
        "/root/data": modal.Volume.from_name("data", create_if_missing=True),
    },
)
def launch_ssh(q):
    with modal.forward(22, unencrypted=True) as tunnel:
        host, port = tunnel.tcp_socket
        threading.Thread(target=wait_for_port, args=(host, port, q)).start()

        subprocess.run(["/usr/sbin/sshd", "-D"])  # TODO: I don't know why I need to start this here


@app.function(
    timeout=3600 * 24,
    gpu="T4",
    secrets=[modal.Secret.from_name("wandb-secret")],
    volumes={
        "/root/data": modal.Volume.from_name("data", create_if_missing=True),
    },
)
def run(dataset: str) -> None:
    subprocess.run(["sh", "run.sh", dataset])


@app.local_entrypoint()
def main(dataset: str | None = None, server: bool = False):
    if server:
        import sshtunnel

        with modal.Queue.ephemeral() as q:
            launch_ssh.spawn(q)
            host, port = q.get()
            print(f"SSH server running at {host}:{port}")

            server = sshtunnel.SSHTunnelForwarder(
                (host, port),
                ssh_username="root",
                ssh_password=" ",
                remote_bind_address=("127.0.0.1", 22),
                local_bind_address=("127.0.0.1", LOCAL_PORT),
                allow_agent=False,
            )

            try:
                server.start()
                print(f"SSH tunnel forwarded to localhost:{server.local_bind_port}")
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nShutting down SSH tunnel...")
            finally:
                server.stop()
    elif dataset is not None:
        run.remote(dataset)
