output "node_ips" {
  value = [
    for i, instance in aws_instance.postgres_nodes :
    {
      public_ip  = instance.public_ip
      private_ip = instance.private_ip
    }
  ]
}

output "instance_ids" {
  value = [for instance in aws_instance.postgres_nodes : instance.id]
}

