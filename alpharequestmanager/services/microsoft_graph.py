import httpx
from typing import List, Dict
from alpharequestmanager.utils.config import config

GRAPH_API_ME = "https://graph.microsoft.com/v1.0/me"
GRAPH_API_GROUPS = "https://graph.microsoft.com/v1.0/me/memberOf"
GRAPH_API_SENDMAIL = "https://graph.microsoft.com/v1.0/me/sendMail"
GRAPH_API_USERS = "https://graph.microsoft.com/v1.0/users"

E3_SKU_ID = "6fd2c87f-b296-42f0-b197-1e91e994b900"


async def get_user_profile(access_token: str) -> dict:
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    async with httpx.AsyncClient() as client:
        # User Details mit erweiterten Feldern
        profile_url = (
            GRAPH_API_ME +
            "?$select=displayName,jobTitle,mobilePhone,businessPhones,companyName,streetAddress,officeLocation,city,postalCode"
        )
        r = await client.get(profile_url, headers=headers)
        r.raise_for_status()
        me = r.json()

        # Gruppenmitgliedschaften
        groups_response = await client.get(GRAPH_API_GROUPS, headers=headers)
        groups_response.raise_for_status()
        groups_data = groups_response.json()

    group_names: List[str] = [
        g.get("displayName") for g in groups_data.get("value", [])
        if g.get("@odata.type") == "#microsoft.graph.group"
    ]

    return {
        "phone": ", ".join(me.get("businessPhones", [])) or None,
        "mobile": me.get("mobilePhone"),
        "address": {
            "street": me.get("streetAddress"),
            "zip": me.get("postalCode"),
            "city": me.get("city") or me.get("officeLocation")
        },
        "company": me.get("companyName"),
        "position": me.get("jobTitle"),
        "group_names": group_names
    }


async def send_mail(
    access_token: str,
    subject: str,
    content: str,
    save_to_sent_items: bool = True,
) -> None:
    """Sendet eine E-Mail im Kontext des aktuellen Benutzers."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    body = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": content},
            "toRecipients": [
                {"emailAddress": {"address": config.TICKET_MAIL}}
            ],
        },
        "saveToSentItems": str(save_to_sent_items).lower(),
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(GRAPH_API_SENDMAIL, headers=headers, json=body)
        resp.raise_for_status()


async def list_all_users_appcontext(access_token: str) -> list[dict]:
    """
    Holt alle Benutzer mit App-Only Graph Token.
    Braucht Application Permission: User.Read.All.
    """
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    params = {
        "$top": "999",
        "$select": "id,givenName,surname,displayName,mail,userPrincipalName"
    }

    url = "https://graph.microsoft.com/v1.0/users"
    users = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

            for u in data.get("value", []):
                print(u)
                users.append({
                    "id": u.get("id"),
                    "displayName": u.get("displayName") or "",
                    "mail": u.get("mail") or u.get("userPrincipalName") or "",
                })

            next_link = data.get("@odata.nextLink")
            if not next_link:
                break

            # nextLink enthält Query-Parameters, also params NICHT mehr mitschicken
            url = next_link
            params = None

    return users


async def list_all_users_with_e3_license(access_token: str) -> List[Dict[str, str]]:
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    # Benutzer MIT E3-Lizenz filtern
    params = {
        "$top": "999",
        "$select": "id,displayName,mail,userPrincipalName",
        "$filter": f"assignedLicenses/any(x:x/skuId eq {E3_SKU_ID})"
    }

    url = "https://graph.microsoft.com/v1.0/users"
    users: List[Dict[str, str]] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

            for u in data.get("value", []):

                users.append({
                    "id": u.get("id"),
                    "displayName": u.get("displayName") or "",
                    "mail": u.get("mail") or u.get("userPrincipalName") or "",
                })

            next_link = data.get("@odata.nextLink")
            if not next_link:
                break

            url = next_link
            params = None  # Nicht nochmal Query-Params mitschicken

    return users
