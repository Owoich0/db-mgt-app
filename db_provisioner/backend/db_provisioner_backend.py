import os
import shutil
import subprocess
import sqlite3
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from jinja2 import Environment, FileSystemLoader
from datetime import datetime
import re
import ast
import json
import yaml

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class DeployRequest(BaseModel):
    cluster_name: str
    platform: str
    instance_count: int
    postgresql_version: str
    ami: str = None
    instance_type: str = None
    data_volume_size: int = 0
    allowed_ip_1: str = None
    allowed_ip_2: str = None
    pod_count: int = None

class CreateDBRequest(BaseModel):
    cluster_name: str
    db_name: str

class DropDBRequest(BaseModel):
    cluster_name: str
    db_name: str

class StartRequest(BaseModel):
    cluster_name: str

class DecommissionRequest(BaseModel):
    cluster_name: str

class AddUserRequest(BaseModel):
    cluster_name: str
    username: str
    password: str
    database: str = "postgres"
    roles: list[str] = []

class StopRequest(BaseModel):
    cluster_name: str
    stop_pod: bool = False       # for Kubernetes
    stop_service: bool = False    # for EC2 PostgreSQL service
    stop_server: bool = False    # for either platform

class RemoveUserRequest(BaseModel):
    cluster_name: str
    username: str

OS_AMI_USER_MAPPING = {
    "ami-0a73e96a849c232cc": "rocky",
    "ami-0c2b8ca1dad447f8a": "ubuntu",
    "ami-0de53d8956e8dcf80": "ec2-user",
    "ami-08962a4068733a2b6": "centos"
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
DEPLOYMENTS_DIR = os.path.join(BASE_DIR, "deployments")
db_path = os.path.join(BASE_DIR, "clusters.db")
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

def init_db():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clusters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_name TEXT,
            platform TEXT,
            status TEXT,
            instance_count INTEGER,
            ami TEXT,
            instance_type TEXT,
            data_volume_size INTEGER,
            postgresql_version TEXT,
            allowed_ip_1 TEXT,
            allowed_ip_2 TEXT,
            server_public_ip TEXT,
            public_ip_1 TEXT,
            public_ip_2 TEXT,
            public_ip_3 TEXT,
            public_ip_4 TEXT,
            public_ip_5 TEXT,
            public_ip_6 TEXT,
            public_ip_7 TEXT,
            public_ip_8 TEXT,
            public_ip_9 TEXT,
            private_ip_1 TEXT,
            private_ip_2 TEXT,
            private_ip_3 TEXT,
            private_ip_4 TEXT,
            private_ip_5 TEXT,
            private_ip_6 TEXT,
            private_ip_7 TEXT,
            private_ip_8 TEXT,
            private_ip_9 TEXT,
            deployment_dir TEXT,
            timestamp TEXT,
            pod_count INTEGER
        )
    """)
    conn.commit()
    conn.close()

init_db()

@app.get("/os-options")
def get_os_options():
    return [{"ami": ami, "os": user} for ami, user in OS_AMI_USER_MAPPING.items()]

@app.get("/pg-versions")
def get_pg_versions():
    return ["14", "15", "16"]

@app.get("/clusters")
def list_clusters():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT cluster_name, status, timestamp, platform FROM clusters")
    rows = cursor.fetchall()
    conn.close()
    return [{"name": name, "status": status, "timestamp": ts, "platform": platform} for name, status, ts, platform in rows]

@app.get("/clusters/{cluster_name}/connection_info")
def get_connection_info(cluster_name: str):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT cluster_name, platform, public_ip_1
        FROM clusters
        WHERE cluster_name=?
    """, (cluster_name,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Cluster not found")

    cluster_name, platform, public_ip = row

    port = 5432
    host = public_ip
    if platform == "kubernetes":
        port = 30036  # nodePort hardcoded in service
        connection_string = f'PGPASSWORD=postgres psql -h {public_ip} -p {port} -U postgres -d postgres'
    else:
        connection_string = f'PGPASSWORD=postgres psql -h {public_ip} -p {port} -U postgres -d postgres'

    return {
        "Host": host,
        "port": port,
        "user": "postgres",
        "password": "postgres",
        "dbname": "postgres",
        "platform": platform,
        "public_ip": public_ip,
        "connection_string": connection_string
    }


@app.post("/deploy")
def deploy_cluster(request: DeployRequest):
    if request.instance_count > 9:
        raise HTTPException(status_code=400, detail="Maximum 9 instances allowed.")

    cluster_dir = os.path.join(DEPLOYMENTS_DIR, request.cluster_name)
    if os.path.exists(cluster_dir):
        raise HTTPException(status_code=409, detail="Cluster already exists.")

    os.makedirs(cluster_dir, exist_ok=True)

    try:
        internet_ip = requests.get("https://api.ipify.org").text.strip()
        ansible_dst = os.path.join(cluster_dir, "ansible")
        tf_module_dst = os.path.join(cluster_dir, "terraform", "modules", "postgres_ha")
        tfvars_path = os.path.join(tf_module_dst, "terraform.tfvars")
        groupvars_path = os.path.join(ansible_dst, "group_vars", "all.yml")

        shutil.copytree(os.path.join(TEMPLATE_DIR, "ansible"), ansible_dst, dirs_exist_ok=True)
        shutil.copytree(os.path.join(TEMPLATE_DIR, "terraform", "modules", "postgres_ha"), tf_module_dst, dirs_exist_ok=True)

        tf_template = env.get_template("terraform/terraform.tfvars.j2")
        ssh_user = OS_AMI_USER_MAPPING.get(request.ami, "rocky")

        # Determine the EC2 instance count
        ec2_instance_count = 1 if request.platform == "kubernetes" else request.instance_count
        k8s_node_count = request.pod_count if request.platform == "kubernetes" else None

        with open(tfvars_path, "w") as f:
            f.write(tf_template.render(
                cluster_name=request.cluster_name,
                instance_count=ec2_instance_count,
                postgres_version=request.postgresql_version,
                ami=request.ami,
                instance_type=request.instance_type,
                data_volume_size=request.data_volume_size,
                ssh_user=ssh_user,
                key_name="ha-postgres-key",
                public_key_path="~/.ssh/ha-postgres-key.pub",
                allowed_ip_1=request.allowed_ip_1,
                allowed_ip_2=request.allowed_ip_2,
                server_public_ip=internet_ip,
                platform=request.platform,
                pod_count=request.pod_count,
                k8s_node_count=k8s_node_count
            ))

        groupvars_template = env.get_template("ansible/group_vars/all.yml")
        with open(groupvars_path, "w") as f:
            f.write(groupvars_template.render(
                cluster_name=request.cluster_name,
                postgresql_version=request.postgresql_version,
                instance_count=request.instance_count,
                allowed_ips=[request.allowed_ip_1, request.allowed_ip_2],
                server_public_ip=internet_ip,
                platform=request.platform,
                pod_count=request.pod_count if request.platform == "kubernetes" else None,
                k8s_node_count=k8s_node_count
            ))

        subprocess.run(["terraform", "init"], cwd=tf_module_dst, check=True)
        subprocess.run(["terraform", "apply", "-auto-approve"], cwd=tf_module_dst, check=True)

        output_result = subprocess.run(
            ["terraform", "output", "-json"], cwd=tf_module_dst,
            capture_output=True, text=True, check=True
        )
        tf_outputs = json.loads(output_result.stdout)
        instance_ids = tf_outputs.get("instance_ids", {}).get("value", [])
        first_instance_id = instance_ids[0]

        aws_cli_cmd = [
            "aws", "ec2", "describe-instances",
            "--instance-ids", first_instance_id,
            "--query", "Reservations[0].Instances[0].PublicIpAddress",
            "--output", "text"
        ]
        result = subprocess.run(aws_cli_cmd, capture_output=True, text=True, check=True)
        first_public_ip = result.stdout.strip()

        pod_count = int(request.pod_count) if request.pod_count is not None else None

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO clusters (
                cluster_name, platform, instance_count, status, timestamp,
                deployment_dir, ami, instance_type, data_volume_size,
                postgresql_version, allowed_ip_1, allowed_ip_2,
                server_public_ip, pod_count, public_ip_1
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            request.cluster_name, request.platform, request.instance_count,
            "completed", datetime.utcnow().isoformat(), cluster_dir,
            request.ami, request.instance_type, request.data_volume_size,
            request.postgresql_version, request.allowed_ip_1, request.allowed_ip_2,
            internet_ip, pod_count, first_public_ip
        ))

        conn.commit()
        conn.close()

        inventory_path = os.path.join(ansible_dst, "inventory", "inventory.ini")
        if not os.path.exists(inventory_path):
            raise HTTPException(status_code=500, detail="Generated inventory not found.")

    except Exception as e:
        tf_exec_dir = os.path.join(cluster_dir, "terraform", "modules", "postgres_ha")
        try:
            if os.path.exists(tf_exec_dir):
                subprocess.run(["terraform", "destroy", "-auto-approve"], cwd=tf_exec_dir, check=False)
        except Exception as tf_err:
            print(f"Terraform destroy failed during cleanup: {tf_err}")

        shutil.rmtree(cluster_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Provisioning failed: {str(e)}")


#### Create Database ####
@app.post("/create_database")
def create_database(request: CreateDBRequest):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT deployment_dir, platform FROM clusters WHERE cluster_name=?", (request.cluster_name,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Cluster not found")

    deployment_dir, platform = row
    ansible_dir = os.path.join(deployment_dir, "ansible")

    if platform == "kubernetes":
        # Kubernetes playbook
        inventory = os.path.join(ansible_dir, "inventory", "inventory.ini")
        k8s_playbook = os.path.join(ansible_dir, "create_database_k8s.yml")

        if not os.path.exists(k8s_playbook):
            raise HTTPException(status_code=500, detail="Kubernetes create DB playbook not found")

        try:
            subprocess.run([
                "ansible-playbook",
                k8s_playbook, "-i", inventory,
                "-e", f"db_name={request.db_name}",
                "-e", f"cluster_name={request.cluster_name}"
            ], check=True)
            return {"message": f"[Kubernetes] Database '{request.db_name}' created successfully"}
        except subprocess.CalledProcessError as e:
            raise HTTPException(status_code=500, detail=f"[K8s] Failed to create database: {e}")
    else:
        # EC2/Bare-metal playbook
        inventory = os.path.join(ansible_dir, "inventory", "inventory.ini")
        playbook = os.path.join(ansible_dir, "create_database.yml")

        if not os.path.exists(playbook):
            raise HTTPException(status_code=500, detail="create_database.yml not found")

        try:
            subprocess.run([
                "ansible-playbook",
                "-i", inventory,
                playbook,
                "-e", f"db_name={request.db_name}"
            ], check=True)
            return {"message": f"Database '{request.db_name}' created successfully"}
        except subprocess.CalledProcessError as e:
            raise HTTPException(status_code=500, detail=f"Failed to create database: {e}")

@app.get("/clusters/{cluster_name}/databases")
def list_databases(cluster_name: str):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT deployment_dir, platform FROM clusters WHERE cluster_name=?", (cluster_name,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Cluster not found")

    deployment_dir, platform = row
    ansible_dir = os.path.join(deployment_dir, "ansible")

    if platform == "kubernetes":
        playbook = os.path.join(ansible_dir, "list_databases_k8s.yml")
        inventory = os.path.join(ansible_dir, "inventory", "inventory.ini")
        cmd = ["ansible-playbook", "-i", inventory, playbook]
    else:
        inventory = os.path.join(ansible_dir, "inventory", "inventory.ini")
        playbook = os.path.join(ansible_dir, "list_databases.yml")
        cmd = ["ansible-playbook", "-i", inventory, playbook]

    if not os.path.exists(playbook):
        raise HTTPException(status_code=500, detail="List databases playbook not found")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        
        match = re.search(r'"msg":\s*\[(.*?)\]', result.stdout, re.DOTALL)
        if match:
            db_lines = "[" + match.group(1).strip() + "]"
            try:
                databases = json.loads(db_lines)
                return {"databases": databases}
            except json.JSONDecodeError:
                raise HTTPException(status_code=500, detail="Failed to parse database list from playbook output.")
        return {"databases": []}
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail="Failed to list databases: " + e.stderr.strip())

@app.post("/drop_database")
def drop_database(request: DropDBRequest):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT deployment_dir, platform FROM clusters WHERE cluster_name=?", (request.cluster_name,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Cluster not found")

    deployment_dir, platform = row
    ansible_dir = os.path.join(deployment_dir, "ansible")

    if platform == "kubernetes":
        inventory = os.path.join(ansible_dir, "inventory", "inventory.ini")
        k8s_playbook = os.path.join(deployment_dir, "ansible", "drop_database_k8s.yml")
        if not os.path.exists(k8s_playbook):
            raise HTTPException(status_code=500, detail="drop_database_k8s.yml not found")
        try:
            subprocess.run([
                "ansible-playbook",
                k8s_playbook,
                "-i", inventory,
                "-e", f"db_name={request.db_name}"
            ], check=True)
            return {"message": f"[K8s] Database '{request.db_name}' dropped successfully"}
        except subprocess.CalledProcessError:
            raise HTTPException(status_code=500, detail="[K8s] Failed to drop database")
    else:
        inventory = os.path.join(ansible_dir, "inventory", "inventory.ini")
        playbook = os.path.join(ansible_dir, "drop_database.yml")

        if not os.path.exists(playbook):
            raise HTTPException(status_code=500, detail="Ansible drop_database.yml not found")

        try:
            subprocess.run([
                "ansible-playbook",
                "-i", inventory,
                playbook,
                "-e", f"db_name={request.db_name}"
            ], check=True)
            return {"message": f"Database '{request.db_name}' dropped successfully"}
        except subprocess.CalledProcessError:
            raise HTTPException(status_code=500, detail="Failed to drop database")

@app.post("/decommission")
def decommission_standalone(request: DecommissionRequest):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT instance_count, deployment_dir, platform FROM clusters WHERE cluster_name=?", (request.cluster_name,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Cluster not found")



    instance_count, deployment_dir, platform = row
    ansible_dir = os.path.join(deployment_dir, "ansible")

    if platform == "kubernetes":
        try:
            ###Declare Directory for ansible and script needed
            k8s_cleanup = os.path.join(deployment_dir, "ansible", "k8s_cleanup.yml")
            inventory = os.path.join(ansible_dir, "inventory", "inventory.ini")
            
            ###Run cleanup
            if os.path.exists(k8s_cleanup):
                subprocess.run(["ansible-playbook","-i", inventory, k8s_cleanup], check=True)

            shutil.rmtree(deployment_dir, ignore_errors=True)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM clusters WHERE cluster_name=?", (request.cluster_name,))
            conn.commit()
            conn.close()

            return {"message": f"Kubernetes cluster '{request.cluster_name}' decommissioned successfully"}
        except subprocess.CalledProcessError as e:
            raise HTTPException(status_code=500, detail=f"K8s decommission failed: {str(e)}")
    else:
        if instance_count > 1:
            raise HTTPException(status_code=400, detail="Decommission is only supported for standalone EC2 clusters")

        tf_exec_dir = os.path.join(deployment_dir, "terraform", "modules", "postgres_ha")
        if not os.path.exists(tf_exec_dir):
            raise HTTPException(status_code=500, detail="Terraform path not found")

        try:
            subprocess.run(["terraform", "destroy", "-auto-approve"], cwd=tf_exec_dir, check=True)
            shutil.rmtree(deployment_dir, ignore_errors=True)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM clusters WHERE cluster_name=?", (request.cluster_name,))
            conn.commit()
            conn.close()

            return {"message": f"Cluster '{request.cluster_name}' decommissioned successfully"}
        except subprocess.CalledProcessError as e:
            raise HTTPException(status_code=500, detail="Terraform destroy failed")

@app.post("/add_user")
def add_user(request: AddUserRequest):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT deployment_dir, platform FROM clusters WHERE cluster_name=?", (request.cluster_name,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Cluster not found")

    deployment_dir, platform = row
    ansible_dir = os.path.join(deployment_dir, "ansible")

    if platform == "kubernetes":
        playbook = os.path.join(ansible_dir, "k8s_add_user.yml")
        inventory = os.path.join(ansible_dir, "inventory", "inventory.ini")
    else:
        inventory = os.path.join(ansible_dir, "inventory", "inventory.ini")
        playbook = os.path.join(ansible_dir, "add_user.yml")

    if not os.path.exists(playbook):
        raise HTTPException(status_code=500, detail="Add user playbook not found")

    cmd = ["ansible-playbook"]
    if inventory:
        cmd += ["-i", inventory]
    cmd += [
        playbook,
        "-e", f"db_user={request.username}",
        "-e", f"db_pass={request.password}",
        "-e", f"db_roles={','.join(request.roles)}",
        "-e", f"db_name={request.database}"
    ]

    try:
        subprocess.run(cmd, check=True)
        return {"message": f"User '{request.username}' added successfully"}
    except subprocess.CalledProcessError:
        raise HTTPException(status_code=500, detail="Failed to add user")

@app.post("/remove_user")
def remove_user(request: RemoveUserRequest):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT deployment_dir, platform FROM clusters WHERE cluster_name=?", (request.cluster_name,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Cluster not found")

    deployment_dir, platform = row
    ansible_dir = os.path.join(deployment_dir, "ansible")

    if platform == "kubernetes":
        playbook = os.path.join(ansible_dir, "k8s_remove_user.yml")
        inventory = None
    else:
        inventory = os.path.join(ansible_dir, "inventory", "inventory.ini")
        playbook = os.path.join(ansible_dir, "remove_user.yml")

    if not os.path.exists(playbook):
        raise HTTPException(status_code=500, detail="Remove user playbook not found")

    cmd = ["ansible-playbook"]
    if inventory:
        cmd += ["-i", inventory]
    cmd += [
        playbook,
        "-e", f"db_user={request.username}"
    ]

    try:
        subprocess.run(cmd, check=True)
        return {"message": f"User '{request.username}' removed successfully"}
    except subprocess.CalledProcessError:
        raise HTTPException(status_code=500, detail="Failed to remove user")


@app.get("/standalone_clusters")
def list_standalone_clusters():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT cluster_name, status, timestamp, platform 
        FROM clusters 
        WHERE instance_count = 1
    """)
    rows = cursor.fetchall()
    conn.close()
    return [{"name": name, "status": status, "timestamp": ts, "platform": platform} for name, status, ts, platform in rows]


def is_ec2_server_running(inventory_file: str) -> bool:
    try:
        result = subprocess.run(
            ["ansible", "-i", inventory_file, "all", "-m", "ping"],
            capture_output=True, text=True, check=True
        )
        return "SUCCESS" in result.stdout
    except subprocess.CalledProcessError:
        return False

@app.post("/stop")
def stop_cluster(request: StopRequest):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT deployment_dir, platform FROM clusters WHERE cluster_name=?", (request.cluster_name,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Cluster not found")

    deployment_dir, platform = row
    ansible_dir = os.path.join(deployment_dir, "ansible")
    inventory_file = os.path.join(ansible_dir, "inventory", "inventory.ini")
    messages = []

    try:
        if platform == "kubernetes":
            # If user did not confirm pod stop, cancel entire operation
            if not request.stop_pod:
                return {"message": "PostgreSQL pod stop cancelled. No actions performed."}

            k8s_stop_pod = os.path.join(ansible_dir, "stop_postgres_pod.yml")
            if os.path.exists(k8s_stop_pod):
                subprocess.run(["ansible-playbook","-i", inventory_file, k8s_stop_pod], check=True)
                messages.append("PostgreSQL pod stopped.")
            else:
                messages.append("Pod stop playbook not found.")

            # Now proceed to server stop if requested
            if request.stop_server:
                stop_server_playbook = os.path.join(ansible_dir, "stop_server.yml")
                if os.path.exists(stop_server_playbook):
                    subprocess.run(["ansible-playbook", "-i", inventory_file, stop_server_playbook], check=True)
                    messages.append("EC2 server stopped.")
                else:
                    messages.append("Server stop playbook not found.")

        else:  # platform == "ec2"
            # If user did not confirm stopping postgres service, cancel entirely
            if not request.stop_service:
                return {"message": "PostgreSQL service stop cancelled. No actions performed."}

            stop_pg_playbook = os.path.join(ansible_dir, "stop_instance.yml")
            if os.path.exists(stop_pg_playbook):
                subprocess.run(["ansible-playbook", "-i", inventory_file, stop_pg_playbook], check=True)
                messages.append("PostgreSQL service stopped.")
            else:
                messages.append("PostgreSQL service stop playbook not found.")

            # Now check if they chose to stop EC2 server
            if request.stop_server:
                stop_server_playbook = os.path.join(ansible_dir, "stop_server.yml")
                if os.path.exists(stop_server_playbook):
                    subprocess.run(["ansible-playbook", "-i", inventory_file, stop_server_playbook], check=True)
                    messages.append("EC2 server stopped.")
                else:
                    messages.append("Server stop playbook not found.")

        return {"message": " | ".join(messages) if messages else "No actions performed."}

    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Stop operation failed: {str(e)}")

@app.post("/start")
def start_cluster(request: StartRequest):
    import subprocess
    import re

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT deployment_dir, platform, public_ip_1, cluster_name FROM clusters WHERE cluster_name=?", (request.cluster_name,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Cluster not found")

    deployment_dir, platform, old_ip, cluster_tag = row
    ansible_dir = os.path.join(deployment_dir, "ansible")
    inventory_file = os.path.join(ansible_dir, "inventory", "inventory.ini")
    messages = []

    try:
        # start ec2 server
        start_server_playbook = os.path.join(ansible_dir, "start_server.yml")
        if os.path.exists(start_server_playbook):
            subprocess.run(["ansible-playbook", "-i", inventory_file, start_server_playbook], check=True)
            messages.append("EC2 server started.")
        else:
            raise HTTPException(status_code=500, detail="start_server.yml not found.")

        # Get updated IP using AWS CLI
        aws_cmd = [
            "aws", "ec2", "describe-instances",
            "--filters", f"Name=tag:Name,Values={cluster_tag}-node-1",
            "--query", "Reservations[*].Instances[*].PublicIpAddress",
            "--output", "text"
        ]
        new_ip = subprocess.check_output(aws_cmd, text=True).strip()

        # Update ansible_host IP in inventory.ini
        with open(inventory_file, "r") as f:
            lines = f.readlines()

        with open(inventory_file, "w") as f:
            updated = False
            for line in lines:
                if f"{cluster_tag}-node-1" in line and "ansible_host=" in line:
                    # Use regex to replace the ansible_host IP only
                    new_line = re.sub(r"(ansible_host=)(\S+)", f"\\1{new_ip}", line)
                    f.write(new_line)
                    updated = True
                else:
                    f.write(line)
            if not updated:
                f.write(f"{cluster_tag}-node-1 ansible_host={new_ip} ansible_user=rocky ansible_ssh_private_key_file=~/.ssh/ha-postgres-key\n")



        # Step 4: Update database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE clusters
            SET public_ip_1=?
            WHERE cluster_name=?
        """, (new_ip, request.cluster_name))
        conn.commit()
        conn.close()

        # Step 5: Start PostgreSQL
        if platform == "kubernetes":
            pod_playbook = os.path.join(ansible_dir, "start_postgres_pod.yml")
            if os.path.exists(pod_playbook):
                subprocess.run(["ansible-playbook", "-i", inventory_file, pod_playbook], check=True)
                messages.append("PostgreSQL pod started.")
            else:
                raise HTTPException(status_code=500, detail="start_postgres_pod.yml not found.")
        else:
            service_playbook = os.path.join(ansible_dir, "start_instance.yml")
            if os.path.exists(service_playbook):
                subprocess.run(["ansible-playbook", "-i", inventory_file, service_playbook], check=True)
                messages.append("PostgreSQL service started.")
            else:
                raise HTTPException(status_code=500, detail="start_instance.yml not found.")

        return {"message": " | ".join(messages)}

    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Start operation failed: {str(e)}")

@app.get("/status/{cluster_name}")
def get_cluster_status(cluster_name: str):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clusters WHERE cluster_name = ?", (cluster_name,))
    row = cursor.fetchone()
    columns = [col[0] for col in cursor.description]
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Cluster not found")

    cluster = dict(zip(columns, row))
    deployment_dir = cluster["deployment_dir"]
    platform = cluster["platform"]
    ansible_dir = os.path.join(deployment_dir, "ansible")

    def remove_warnings(output: str) -> str:
        return "\n".join(
            line for line in output.splitlines()
            if not line.strip().startswith("[WARNING]")
        )

    if platform == "kubernetes":
        check_playbook = os.path.join(ansible_dir, "check_postgres_status_k8s.yml")
        inventory_file = os.path.join(ansible_dir, "inventory", "inventory.ini")

        if not os.path.exists(check_playbook) or not os.path.exists(inventory_file):
            cluster["is_running"] = "unknown"
            return cluster

        try:
            result = subprocess.run(
                ["ansible-playbook", "-i", inventory_file, check_playbook],
                capture_output=True,
                text=True
            )
            clean_stdout = remove_warnings(result.stdout)
            match = re.search(r'db_status=([a-zA-Z]+)', clean_stdout)
            if match:
                cluster["is_running"] = match.group(1).lower()
            else:
                cluster["is_running"] = "unknown"

            if result.returncode != 0:
                cluster["ansible_error"] = result.stderr.strip() or clean_stdout.strip() or "K8s status playbook failed"

        except Exception as e:
            cluster["is_running"] = "error"
            cluster["ansible_error"] = str(e)

    else:
        inventory_file = os.path.join(ansible_dir, "inventory", "inventory.ini")
        check_playbook = os.path.join(ansible_dir, "check_postgres_status.yml")

        if not os.path.exists(check_playbook):
            cluster["is_running"] = "unknown"
            return cluster

        try:
            result = subprocess.run(
                ["ansible-playbook", "-i", inventory_file, check_playbook],
                capture_output=True,
                text=True
            )
            clean_stdout = remove_warnings(result.stdout)
            clean_stderr = remove_warnings(result.stderr)
            stdout_lower = clean_stdout.lower()

            if "is_running=true" in stdout_lower:
                cluster["is_running"] = True
            elif "is_running=false" in stdout_lower:
                cluster["is_running"] = False
            else:
                cluster["is_running"] = "unknown"

            if result.returncode != 0:
                cluster["ansible_error"] = clean_stderr.strip() or clean_stdout.strip() or "Playbook failed"

        except Exception as e:
            cluster["is_running"] = "error"
            cluster["ansible_error"] = str(e)

    return cluster
