#!/bin/bash

CONFIG_FILE="/etc/pgbackrest/pgbackrest.conf"
PGDATA_PATH="/var/lib/pgsql/data/pgdata"
STANZA_NAME="main"

# --- Step 1: Gather Cluster Info -------------------------------------

# Get this node's private IP
LOCAL_IP=$(hostname -I | awk '{print $1}')

# Determine if this node is a replica
IS_REPLICA=$(psql -U postgres -tAc "SELECT pg_is_in_recovery();" | tr -d '[:space:]')

# Get Patroni node name
LOCAL_PATRONI_NAME=$(curl -s http://${LOCAL_IP}:8008 | jq -r '.patroni.name')

# Get full cluster state
CLUSTER_JSON=$(curl -s http://${LOCAL_IP}:8008/cluster)

# Get current leader name and IP
LEADER_NAME=$(echo "$CLUSTER_JSON" | jq -r '.members[] | select(.role == "leader") | .name' | tr -d '[:space:]')
LEADER_IP=$(echo "$CLUSTER_JSON" | jq -r --arg LEADER_NAME "$LEADER_NAME" '.members[] | select(.name == $LEADER_NAME) | .host')

# Build sorted list of replicas
REPLICA_NODES=()
for row in $(echo "$CLUSTER_JSON" | jq -c '.members[]'); do
  ROLE=$(echo "$row" | jq -r '.role')
  NAME=$(echo "$row" | jq -r '.name')
  if [ "$ROLE" = "replica" ]; then
    REPLICA_NODES+=("$NAME")
  fi
done

IFS=$'\n' SORTED_REPLICAS=($(sort <<<"${REPLICA_NODES[*]}"))
PRIMARY_REPLICA="${SORTED_REPLICAS[0]}"

# --- Step 2: Load Existing Global pgBackRest Settings ------------------------

get_config_value() {
    grep -E "^$1\s*=" "$CONFIG_FILE" | awk -F'=' '{print $2}' | xargs
}

REPO1_TYPE=$(get_config_value "repo1-type")
REPO1_PATH=$(get_config_value "repo1-path")
REPO1_BUCKET=$(get_config_value "repo1-s3-bucket")
REPO1_ENDPOINT=$(get_config_value "repo1-s3-endpoint")
REPO1_REGION=$(get_config_value "repo1-s3-region")
REPO1_KEY=$(get_config_value "repo1-s3-key")
REPO1_SECRET=$(get_config_value "repo1-s3-key-secret")
REPO1_VERIFY_TLS=$(get_config_value "repo1-storage-verify-tls")
REPO1_VERIFY_TLS="${REPO1_VERIFY_TLS:-y}"
REPO1_RET_FULL=$(get_config_value "repo1-retention-full")
REPO1_RET_DIFF=$(get_config_value "repo1-retention-diff")
LOG_LEVEL_CONSOLE=$(get_config_value "log-level-console")
LOG_LEVEL_FILE=$(get_config_value "log-level-file")
LOG_PATH=$(get_config_value "log-path")

# --- Step 3: Rewrite pgBackRest Configuration ------------------------

echo "[INFO] Writing pgBackRest config to $CONFIG_FILE..."
{
  echo "[global]"
  echo "repo1-type=${REPO1_TYPE}"
  echo "repo1-path=${REPO1_PATH}"
  echo "repo1-s3-bucket=${REPO1_BUCKET}"
  echo "repo1-s3-endpoint=${REPO1_ENDPOINT}"
  echo "repo1-s3-region=${REPO1_REGION}"
  echo "repo1-s3-key=${REPO1_KEY}"
  echo "repo1-s3-key-secret=${REPO1_SECRET}"
  echo "repo1-storage-verify-tls=${REPO1_VERIFY_TLS}"
  echo "repo1-retention-full=${REPO1_RET_FULL}"
  echo "repo1-retention-diff=${REPO1_RET_DIFF}"
  echo "log-level-console=${LOG_LEVEL_CONSOLE}"
  echo "log-level-file=${LOG_LEVEL_FILE}"
  echo "log-path=${LOG_PATH}"
  echo "start-fast=y"
  echo "compress-level=3"
  echo "process-max=4"
  echo "delta=y"
  echo ""
  echo "[$STANZA_NAME]"

  if [ "$LOCAL_IP" != "$LEADER_IP" ]; then
    echo "pg1-host=${LEADER_IP}"
    echo "pg2-path=${PGDATA_PATH}"
    echo "pg2-port=5432"
  fi

  echo "pg1-path=${PGDATA_PATH}"
  echo "pg1-port=5432"
} > "$CONFIG_FILE"

# --- Step 4: Run stanza-create if needed -----------------------------

if [ "$IS_REPLICA" = "t" ] && [ "$LOCAL_PATRONI_NAME" = "$PRIMARY_REPLICA" ]; then
    if [ ! -f "/var/lib/pgbackrest/backup/${STANZA_NAME}/backup.info" ]; then
        echo "[INFO] Running stanza-create on $LOCAL_PATRONI_NAME..."
        /usr/bin/pgbackrest --stanza=$STANZA_NAME stanza-create
    else
        echo "[SKIP] Stanza already exists on $LOCAL_PATRONI_NAME."
    fi
fi

# --- Step 5: Run backup if this is the designated replica ------------

if [ "$IS_REPLICA" = "t" ] && [ "$LOCAL_PATRONI_NAME" = "$PRIMARY_REPLICA" ]; then
    echo "[INFO] Running pgBackRest backup on $LOCAL_PATRONI_NAME..."
    /usr/bin/pgbackrest --stanza=$STANZA_NAME --type=${1:-full} backup --backup-standby=y
else
    echo "[SKIP] Not the designated replica for backup on $LOCAL_PATRONI_NAME."
fi
