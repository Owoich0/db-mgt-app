# db-mgt-app
![k8](https://github.com/Owoich0/db-mgt-app/blob/main/hapr.jpg) ![bare](https://github.com/Owoich0/db-mgt-app/blob/main/REST.jpg)

A self-service platform to **provision**, **connect**, **manage**, and **decommission** PostgreSQL instances and clusters across EC2(K8 and on host) environments.
## 🛠️ Technologies Used

| Layer               | Technology                  |
|---------------------|-----------------------------|
| Web UI              | HTML, CSS, JS (Vanilla)     |
| Backend API         | FastAPI (Python 3.9+)       |
| Provisioning        | Terraform                   |
| Configuration Mgmt  | Ansible                     |
| Database Layer      | PostgreSQL, Patroni         |
| HA & Load Balancing | Keepalived, HAProxy         |
| Backup              | pgBackRest (S3)             |
| Kubernetes          | K3s                         |
| State Management    | SQLite                      |
