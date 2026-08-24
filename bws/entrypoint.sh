#!/bin/sh
set -euo pipefail

export BWS_SERVER_URL="https://vault.bitwarden.eu"
export BWS_ACCESS_TOKEN="$(tr -d '\r\n' < /secrets/bws_token.txt)"

OUT=/runtime-secrets
mkdir -p "$OUT"

fetch() {
    bws secret get "$1" --server-url "$BWS_SERVER_URL" --output json | jq -er '.value' > "$OUT/$2"
}

fetch c96ed7e4-0fb3-4dab-886b-b49301554c7b .htpasswd
fetch 559eac53-d23d-4434-be66-b4930155b4fe django_secret_key.txt
fetch 05c41721-978b-4a7a-9e05-b4930159cb72 google_sheet_id.json
fetch bc6d4366-ddf1-4720-a04c-b49301594b87 google_sheets_key.json
fetch dbc0f755-95db-4d52-86a7-b4930155fa03 postgres_db.txt
fetch ebce5d26-88a5-4843-b378-b49301562c64 postgres_password.txt
fetch f44e3d07-b608-46b4-8565-b4930156541c postgres_user.txt
fetch 5e85bdd8-0df0-4dce-b0c9-b49b00a1ec51 seven_api_key.txt
fetch 001864de-5c33-4216-bada-b4a500919e36 ntfy_password.txt
fetch 489746e5-b445-4cdc-af92-b4a50092af89 ntfy_password_mz.txt
fetch ee333081-ead5-4f07-aa96-b4a50092d2ba ntfy_password.vp.txt
fetch daac5d3e-52e0-414f-b0a8-b49f00907b85 ntfy_user.txt
fetch 954b0f69-80e8-4a51-9c12-b4a500926b5a ntfy_user_mz.txt
fetch bca78245-3276-43ec-b4f5-b4a50092803c ntfy_user_vp.txt
#fetch 4ea1edd7-ca67-446a-a70a-b4af014b56d5 keepalive_phone_number.txt


echo "All secrets fetched successfully."
