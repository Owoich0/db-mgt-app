[postgresql]
%{ for node in nodes ~}
${node.name} ansible_host=${node.public_ip} ansible_user=rocky ansible_ssh_private_key_file=~/.ssh/ha-postgres-key private_ip=${node.private_ip}
%{ endfor ~}

[postgresql:vars]
server_public_ip={{ server_public_ip }}

[all:vars]
ansible_python_interpreter=/usr/bin/python3
