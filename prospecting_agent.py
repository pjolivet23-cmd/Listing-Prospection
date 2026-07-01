#!/usr/bin/env python3
"""
Agent de prospection B2B — Astridsen (nucléaire / énergies)
Recherche Lusha + enrichissement + vérification BoondManager + export CSV
"""

import os
import sys
import csv
import time
import logging
from datetime import datetime
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# ─── Configuration ─────────────────────────────────────────────────────────────

LUSHA_API_KEY = os.getenv("LUSHA_API_KEY", "")
BOOND_LOGIN = os.getenv("BOOND_LOGIN", "")
BOOND_PASSWORD = os.getenv("BOOND_PASSWORD", "")
BOOND_BASE_URL = os.getenv("BOOND_BASE_URL", "https://ui.boondmanager.com/api")

SEARCH_CONFIG = {
    "segments_actifs": "tous",
    "max_results_par_segment": 20,
    "reveler_telephones": True,
    "output_file": None,
}

SEGMENTS = [
    {
        "nom": "Exploitants nucléaires",
        "job_titles": [
            "Directeur de Projet", "Chef de Projet", "Directeur de Programme",
            "Responsable Ingénierie", "Directeur Ingénierie",
            "Responsable Bureau d'Etudes", "Directeur Bureau d'Etudes",
            "Directeur Maintenance", "Responsable Maintenance",
            "Directeur des Operations", "Directeur d'Unite",
            "Responsable Surete Nucleaire", "Responsable Qualite Nucleaire",
        ],
        "industry_labels": ["Oil & Energy", "Utilities", "Nuclear"],
        "keywords": ["centrale nucleaire", "reacteur", "CNPE", "surete nucleaire",
                     "demantelement", "combustible nucleaire"],
    },
    {
        "nom": "Maitres d'oeuvre & ingenierie nucleaire",
        "job_titles": [
            "Directeur de Projet", "Directeur d'Affaires", "Manager d'Affaires",
            "Directeur Technique", "Chef de Departement Technique",
            "Directeur d'Agence", "Responsable Bureau d'Etudes",
            "Responsable Ressources Techniques", "Chef de Projet",
        ],
        "industry_labels": ["Industrial Automation", "Mechanical or Industrial Engineering",
                            "Defense & Space", "Oil & Energy"],
        "keywords": ["ingenierie nucleaire", "maitrise d'oeuvre", "I&C nucleaire",
                     "protection radiologique", "ingenierie de surete"],
    },
    {
        "nom": "Maintenance & travaux nucleaires",
        "job_titles": [
            "Directeur des Operations", "Directeur d'Affaires",
            "Directeur de Site", "Directeur d'Etablissement",
            "Responsable Travaux", "Directeur Travaux",
            "Chef de Chantier", "Chef de Travaux",
            "Directeur Maintenance", "Responsable Maintenance",
            "Chef de Projet", "Directeur Technique",
        ],
        "industry_labels": ["Mechanical or Industrial Engineering", "Oil & Energy",
                            "Construction", "Utilities"],
        "keywords": ["maintenance nucleaire", "arret de tranche", "travaux CNPE",
                     "robinetterie nucleaire", "habilitation nucleaire"],
    },
    {
        "nom": "Fournisseurs d'equipements & sous-traitants",
        "job_titles": [
            "Directeur d'Affaires", "Responsable d'Affaires",
            "Directeur Industriel", "Directeur de Production",
            "Directeur Technique", "Chef de Projet",
            "Responsable Bureau d'Etudes", "Directeur de Site", "Directeur General",
        ],
        "industry_labels": ["Mechanical or Industrial Engineering", "Machinery",
                            "Electrical/Electronic Manufacturing", "Oil & Energy"],
        "keywords": ["equipements nucleaires", "chaudronnerie nucleaire",
                     "tuyauterie industrielle", "qualification nucleaire"],
    },
    {
        "nom": "Bureaux d'etudes specialises",
        "job_titles": [
            "Directeur d'Agence", "Directeur Bureau d'Etudes",
            "Responsable Bureau d'Etudes", "Responsable d'Affaires",
            "Chef de Projet", "Directeur Technique",
            "Chef de Departement", "Directeur General",
        ],
        "industry_labels": ["Civil Engineering", "Architecture & Planning",
                            "Mechanical or Industrial Engineering", "Environmental Services"],
        "keywords": ["bureau d'etudes nucleaire", "genie civil nucleaire",
                     "ingenierie de surete", "thermique industrielle"],
    },
]

# ─── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─── Lusha helpers ─────────────────────────────────────────────────────────────

def _lusha_post(endpoint: str, body: dict, retry: int = 1) -> Optional[dict]:
    url = f"https://api.lusha.com/v3{endpoint}"
    headers = {"api_key": LUSHA_API_KEY, "Content-Type": "application/json"}
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=30)
        if resp.status_code == 429:
            if retry > 0:
                logger.warning("⚠️  Lusha 429 — attente 60s…")
                time.sleep(60)
                return _lusha_post(endpoint, body, retry=retry - 1)
            logger.error("⚠️  Lusha 429 persistant — abandon")
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("⚠️  Lusha erreur réseau : %s", exc)
        return None


def search_contacts_lusha(segment: dict, max_results: int = 20) -> list[dict]:
    """Pagine les résultats Lusha jusqu'à max_results."""
    collected: list[dict] = []
    page = 1
    size = min(50, max_results)

    while len(collected) < max_results:
        body = {
            "pagination": {"page": page, "size": size},
            "filters": {
                "contacts": {
                    "include": {
                        "countries": ["FR"],
                        "jobTitles": segment["job_titles"],
                        "existingDataPoints": ["work_email", "work_phone"],
                    }
                },
                "companies": {
                    "include": {
                        "keywords": segment["keywords"],
                        "industriesLabels": segment["industry_labels"],
                    }
                },
            },
            "options": {"excludeDnc": True},
        }
        data = _lusha_post("/contacts/prospecting", body)
        if not data:
            break

        results = data.get("results") or []
        if not results:
            break

        collected.extend(results)
        total = (data.get("pagination") or {}).get("total", 0)
        if len(collected) >= total or len(collected) >= max_results:
            break

        page += 1
        size = min(50, max_results - len(collected))

    return collected[:max_results]


def enrich_contacts_lusha(contacts: list[dict], reveler_tel: bool = True) -> dict[str, dict]:
    """Révèle emails et téléphones pour les contacts éligibles."""
    to_reveal = []
    for c in contacts:
        can_reveal = c.get("canReveal") or []
        fields = []
        if "emails" in can_reveal:
            fields.append("emails")
        if reveler_tel and "phones" in can_reveal:
            fields.append("phones")
        if fields:
            to_reveal.append({"id": c["id"], "reveal": fields})

    if not to_reveal:
        return {}

    # Lusha enrich accepte jusqu'à 25 contacts par appel
    enriched: dict[str, dict] = {}
    batch_size = 25
    for i in range(0, len(to_reveal), batch_size):
        batch = to_reveal[i : i + batch_size]
        data = _lusha_post("/contacts/enrich", {"contacts": batch})
        if not data:
            continue
        for item in data.get("results") or []:
            cid = item.get("id")
            if not cid:
                continue
            error = item.get("error") or {}
            if error.get("code") in ("NOT_FOUND", "COMPLIANCE_RESTRICTED"):
                logger.warning("⚠️  Contact %s : %s", cid, error.get("code"))
                continue
            emails = item.get("emails") or []
            phones = item.get("phones") or []
            enriched[str(cid)] = {
                "email": emails[0].get("email") if emails else "",
                "phone": phones[0].get("normalizedPhone") or phones[0].get("phone") if phones else "",
            }

    return enriched


# ─── BoondManager helpers ──────────────────────────────────────────────────────

def _boond_get(path: str, params: Optional[dict] = None, retry: int = 1) -> Optional[dict]:
    url = f"{BOOND_BASE_URL}{path}"
    try:
        resp = requests.get(
            url,
            params=params,
            auth=(BOOND_LOGIN, BOOND_PASSWORD),
            timeout=30,
        )
        if resp.status_code == 401:
            logger.error("Credentials Boond invalides — arrêt.")
            sys.exit(1)
        if resp.status_code == 404:
            return None
        if resp.status_code == 429:
            if retry > 0:
                logger.warning("⚠️  BoondManager 429 — attente 30s…")
                time.sleep(30)
                return _boond_get(path, params, retry=retry - 1)
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("⚠️  BoondManager erreur réseau : %s", exc)
        return None


def get_derniere_action_boond(contact_id: str) -> dict:
    """Récupère la dernière action/interaction liée à un contact Boond."""
    data = _boond_get(f"/contacts/{contact_id}/actions", params={"maxResults": 1, "page": 1})
    if not data:
        return {}
    actions = data.get("data") or []
    if not actions:
        return {}
    first = actions[0]
    attrs = first.get("attributes") or first  # handle flat or nested structure
    date_val = attrs.get("startDate") or attrs.get("date") or ""
    subject = attrs.get("title") or attrs.get("subject") or ""
    return {"date": date_val, "sujet": subject}


def check_contact_boond(prenom: str, nom: str) -> dict:
    """Cherche un contact dans BoondManager par prénom + nom."""
    empty = {
        "existe": False,
        "statut": "inconnu",
        "derniere_action_date": "",
        "derniere_action_sujet": "",
        "responsable": "",
    }
    if not (prenom or nom):
        return empty

    keyword = f"{prenom} {nom}".strip()
    data = _boond_get("/contacts", params={"keywords": keyword, "maxResults": 5})
    if not data:
        return empty

    contacts = data.get("data") or []
    # Chercher correspondance exacte prénom + nom (insensible à la casse)
    match = None
    for c in contacts:
        attrs = c.get("attributes") or c
        fn = (attrs.get("firstName") or "").strip().lower()
        ln = (attrs.get("lastName") or "").strip().lower()
        if fn == prenom.lower() and ln == nom.lower():
            match = c
            break
    if not match and contacts:
        # Fallback : prendre le premier résultat si recherche peu ambiguë
        match = contacts[0]

    if not match:
        return empty

    contact_id = match.get("id") or (match.get("data") or {}).get("id")
    attrs = match.get("attributes") or match

    # Statut de l'entreprise liée (via relationships)
    statut = "inconnu"
    rels = match.get("relationships") or {}
    company_data = (rels.get("company") or {}).get("data") or {}
    company_id = company_data.get("id")
    if company_id:
        comp = _boond_get(f"/companies/{company_id}")
        if comp:
            comp_attrs = (comp.get("data") or {}).get("attributes") or {}
            state = comp_attrs.get("state") or comp_attrs.get("status") or ""
            state_map = {"1": "client", "2": "prospect", "3": "ex-client", "client": "client",
                         "prospect": "prospect", "ex-client": "ex-client"}
            statut = state_map.get(str(state).lower(), str(state) or "inconnu")

    # Responsable Astridsen
    manager_data = (rels.get("mainManager") or {}).get("data") or {}
    manager_id = manager_data.get("id")
    responsable = attrs.get("mainManagerName") or ""
    if not responsable and manager_id:
        mgr = _boond_get(f"/resources/{manager_id}")
        if mgr:
            mgr_attrs = (mgr.get("data") or {}).get("attributes") or {}
            responsable = f"{mgr_attrs.get('firstName', '')} {mgr_attrs.get('lastName', '')}".strip()

    derniere_action = get_derniere_action_boond(str(contact_id)) if contact_id else {}

    return {
        "existe": True,
        "statut": statut,
        "derniere_action_date": derniere_action.get("date", ""),
        "derniere_action_sujet": derniere_action.get("sujet", ""),
        "responsable": responsable,
    }


def check_company_boond(nom_entreprise: str) -> dict:
    """Vérifie si l'entreprise est connue dans BoondManager."""
    if not nom_entreprise:
        return {"existe": False, "statut": "inconnu"}
    data = _boond_get("/companies", params={"keywords": nom_entreprise, "maxResults": 3})
    if not data:
        return {"existe": False, "statut": "inconnu"}
    companies = data.get("data") or []
    if not companies:
        return {"existe": False, "statut": "inconnu"}
    attrs = (companies[0].get("attributes") or companies[0])
    state = attrs.get("state") or attrs.get("status") or ""
    state_map = {"1": "client", "2": "prospect", "3": "ex-client"}
    statut = state_map.get(str(state), str(state) or "inconnu")
    return {"existe": True, "statut": statut}


# ─── CSV export ────────────────────────────────────────────────────────────────

CSV_FIELDS = [
    "prenom", "nom", "titre_poste", "seniority", "entreprise", "domaine_web",
    "segment_cible", "ville", "pays", "linkedin_url", "email", "telephone",
    "boond_contact_connu", "boond_statut_entreprise",
    "boond_derniere_action_date", "boond_derniere_action_sujet",
    "boond_responsable_astridsen", "date_extraction",
]


def export_to_csv(prospects: list[dict], filename: Optional[str] = None) -> str:
    if not filename:
        filename = f"prospects_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(prospects)
    return filename


# ─── Display helpers ───────────────────────────────────────────────────────────

def _boond_emoji(info: dict) -> str:
    if not info.get("existe"):
        return "⚪"
    statut = (info.get("statut") or "").lower()
    return {"client": "🟢", "prospect": "🟡", "ex-client": "🔴"}.get(statut, "⚪")


def _display_contact(idx: int, contact: dict, enrich: dict, boond: dict):
    prenom = contact.get("firstName", "")
    nom = contact.get("lastName", "")
    titre = (contact.get("jobTitle") or {}).get("title", "")
    entreprise = (contact.get("company") or {}).get("name", "")
    email = enrich.get("email") or "(non trouvé)"
    phone = enrich.get("phone") or "(non trouvé)"

    print(f"  ✓ [{idx}] {prenom} {nom} — {titre} — {entreprise}")
    print(f"         📧 {email}  📞 {phone}")

    emoji = _boond_emoji(boond)
    if boond.get("existe"):
        statut = (boond.get("statut") or "").upper()
        date_action = boond.get("derniere_action_date", "")
        sujet = boond.get("derniere_action_sujet", "")
        responsable = boond.get("responsable", "")
        action_str = f'{date_action} "{sujet}"' if date_action else "(aucune action)"
        print(f"         {emoji} BOOND : {statut} — {action_str}")
        if responsable:
            print(f"         👤 Responsable : {responsable}")
    else:
        print(f"         {emoji} BOOND : INCONNU — Premier contact possible")


# ─── Main pipeline ─────────────────────────────────────────────────────────────

def run(config: Optional[dict] = None):
    cfg = {**SEARCH_CONFIG, **(config or {})}

    if not LUSHA_API_KEY:
        logger.error("LUSHA_API_KEY manquante dans .env")
        sys.exit(1)

    segments = SEGMENTS
    if cfg["segments_actifs"] != "tous":
        noms = cfg["segments_actifs"]
        if isinstance(noms, str):
            noms = [noms]
        segments = [s for s in SEGMENTS if s["nom"] in noms]

    max_results = cfg["max_results_par_segment"]
    reveler_tel = cfg["reveler_telephones"]
    output_file = cfg["output_file"]

    all_prospects: list[dict] = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total_emails = 0
    total_phones = 0
    total_clients = 0
    total_prospects_boond = 0

    for segment in segments:
        sep = "━" * 50
        print(f"\n{sep}")
        print(f"🔍 SEGMENT : {segment['nom']}")
        print(sep)

        raw_contacts = search_contacts_lusha(segment, max_results=max_results)
        if not raw_contacts:
            print("  ⚠️  Aucun contact trouvé pour ce segment.")
            continue

        enrich_map = enrich_contacts_lusha(raw_contacts, reveler_tel=reveler_tel)

        seg_emails = 0
        seg_phones = 0

        for idx, c in enumerate(raw_contacts, 1):
            cid = str(c.get("id", ""))
            enrich = enrich_map.get(cid, {})

            prenom = c.get("firstName", "")
            nom = c.get("lastName", "")

            boond = check_contact_boond(prenom, nom)
            if not boond["existe"]:
                entreprise_name = (c.get("company") or {}).get("name", "")
                if entreprise_name:
                    comp_check = check_company_boond(entreprise_name)
                    if boond["statut"] == "inconnu":
                        boond["statut"] = comp_check.get("statut", "inconnu")

            _display_contact(idx, c, enrich, boond)

            email = enrich.get("email", "")
            phone = enrich.get("phone", "")
            if email:
                seg_emails += 1
            if phone:
                seg_phones += 1

            statut_boond = (boond.get("statut") or "").lower()
            if statut_boond == "client":
                total_clients += 1
            elif statut_boond == "prospect":
                total_prospects_boond += 1

            job = c.get("jobTitle") or {}
            location = c.get("location") or {}
            company = c.get("company") or {}
            social = c.get("socialLinks") or {}

            all_prospects.append({
                "prenom": prenom,
                "nom": nom,
                "titre_poste": job.get("title", ""),
                "seniority": job.get("seniority", ""),
                "entreprise": company.get("name", ""),
                "domaine_web": company.get("domain", ""),
                "segment_cible": segment["nom"],
                "ville": location.get("city", ""),
                "pays": location.get("country", ""),
                "linkedin_url": social.get("linkedin", ""),
                "email": email,
                "telephone": phone,
                "boond_contact_connu": "oui" if boond["existe"] else "non",
                "boond_statut_entreprise": boond.get("statut", "inconnu"),
                "boond_derniere_action_date": boond.get("derniere_action_date", ""),
                "boond_derniere_action_sujet": boond.get("derniere_action_sujet", ""),
                "boond_responsable_astridsen": boond.get("responsable", ""),
                "date_extraction": now_str,
            })

        total_emails += seg_emails
        total_phones += seg_phones

        print(f"\n{sep}")
        print(f"✅ Segment : {len(raw_contacts)} contacts | {seg_emails} emails | {seg_phones} tél.")
        print(sep)

    if not all_prospects:
        print("\n⚠️  Aucun prospect collecté. Vérifiez vos clés API.")
        return

    fname = export_to_csv(all_prospects, output_file)
    nouveaux = len(all_prospects) - total_clients - total_prospects_boond
    print(f"\n✅ EXPORT FINAL : {fname}")
    print(f"   → {len(all_prospects)} contacts | {total_emails} emails | {total_phones} téléphones")
    print(f"   → {total_clients} clients Boond | {total_prospects_boond} prospects connus | {nouveaux} nouveaux")


if __name__ == "__main__":
    run()
