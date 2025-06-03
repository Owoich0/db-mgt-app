variable "key_name" {
  description = "Name of the SSH key pair"
  type        = string
}

variable "public_key_path" {
  description = "Path to the public key file"
  type        = string
  default     = "~/.ssh/ha-postgres-key.pub"
}

variable "ami" {
  description = "AMI to use for EC2 instances"
  type        = string
  default     = "ami-0a73e96a849c232cc"
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.small"
}

variable "data_volume_size" {
  description = "Size of the EBS volume for PostgreSQL data"
  type        = number
  default     = 50
}

variable "instance_count" {
  description = "Number of EC2 instances to provision"
  type        = number
  default     = 3
}

variable "cluster_name" {
  description = "Name of the PostgreSQL cluster"
  type        = string
}

variable "postgres_version" {
  description = "Version of PostgreSQL to install"
  type        = string
}

variable "create_key_pair" {
  description = "Whether to create a new key pair"
  type        = bool
  default     = false
}

variable "ssh_user" {
  description = "SSH username for EC2 instance access"
  type        = string
  default     = "ec2-user"
}

variable "platform" {
  description = "Deployment platform: ec2 or kubernetes"
  type        = string
}

variable "allowed_ip_1" {
  description = "First IP address allowed to access the instance"
  type        = string
}

variable "allowed_ip_2" {
  description = "Second IP address allowed to access the instance"
  type        = string
}

variable "pod_count" {
  description = "Number of PostgreSQL pods in Kubernetes"
  type        = number
  default     = 1
}

variable "k8s_node_count" {
  description = "Number of PostgreSQL nodes in Kubernetes"
  type        = number
  default     = 1
}
