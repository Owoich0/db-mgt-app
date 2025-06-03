module "postgres_ha" {
    source = "./modules/postgres_ha"
    key_name = "ha-postgres-key"
}
