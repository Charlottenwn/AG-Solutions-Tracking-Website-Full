#!/bin/sh
set -eu

export BWS_SERVER_URL="https://vault.bitwarden.eu"
export BWS_ACCESS_TOKEN="$(tr -d '\r\n' < /secrets/bws_token.txt)"

OUT=/runtime-secrets
mkdir -p "$OUT"

fetch() {
    bws secret get "$1" --output json | jq -r '.value' > "$OUT/$2"
}

fetch c96ed7e4-0fb3-4dab-886b-b49301554c7b .htpasswd
fetch 559eac53-d23d-4434-be66-b4930155b4fe django_secret_key.txt
fetch 05c41721-978b-4a7a-9e05-b4930159cb72 google_sheet_id.json
fetch bc6d4366-ddf1-4720-a04c-b49301594b87 google_sheets_key.json
fetch dbc0f755-95db-4d52-86a7-b4930155fa03 postgres_db.txt
fetch ebce5d26-88a5-4843-b378-b49301562c64 postgres_password.txt
fetch f44e3d07-b608-46b4-8565-b4930156541c postgres_user.txt

echo "All secrets fetched successfully."