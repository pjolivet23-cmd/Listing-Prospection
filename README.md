# Agent de Prospection B2B — Astridsen

Recherche automatisée de contacts décideurs (nucléaire / énergies) via **Lusha API v3**, enrichissement email/téléphone, vérification **BoondManager** et export CSV.

## Prérequis

- Python 3.10+
- Clé API Lusha (v3)
- Identifiants BoondManager (login + mot de passe)

## Installation

```bash
pip install -r requirements.txt
cp .env.example .env
# Remplir .env avec vos clés
```

## Configuration `.env`

```
LUSHA_API_KEY=votre_cle_lusha
BOOND_LOGIN=votre_login_boond
BOOND_PASSWORD=votre_mot_de_passe
BOOND_BASE_URL=https://ui.boondmanager.com/api
```

## Lancement

```bash
# Lancement standard (tous segments, 20 contacts max/segment)
python prospecting_agent.py

# Personnalisation via code : modifier SEARCH_CONFIG dans le script
# ou appeler run() avec un dict config
```

### Paramètres `SEARCH_CONFIG`

| Paramètre | Défaut | Description |
|---|---|---|
| `segments_actifs` | `"tous"` | `"tous"` ou liste de noms de segments |
| `max_results_par_segment` | `20` | Contacts max par segment |
| `reveler_telephones` | `True` | `False` = emails uniquement (économise crédits Lusha) |
| `output_file` | `None` | Nom du CSV (auto si `None`) |

### Exemple test rapide (1 segment, 3 contacts)

```python
from prospecting_agent import run
run({
    "segments_actifs": ["Exploitants nucléaires"],
    "max_results_par_segment": 3,
    "reveler_telephones": False,
})
```

## Segments couverts

1. Exploitants nucléaires
2. Maîtres d'œuvre & ingénierie nucléaire
3. Maintenance & travaux nucléaires
4. Fournisseurs d'équipements & sous-traitants
5. Bureaux d'études spécialisés

## Format du CSV de sortie

| Colonne | Source |
|---|---|
| `prenom` / `nom` | Lusha |
| `titre_poste` / `seniority` | Lusha |
| `entreprise` / `domaine_web` | Lusha |
| `segment_cible` | Config |
| `ville` / `pays` | Lusha |
| `linkedin_url` | Lusha |
| `email` / `telephone` | Lusha Enrich |
| `boond_contact_connu` | BoondManager (oui/non) |
| `boond_statut_entreprise` | BoondManager (client/prospect/ex-client/inconnu) |
| `boond_derniere_action_date` | BoondManager |
| `boond_derniere_action_sujet` | BoondManager |
| `boond_responsable_astridsen` | BoondManager |
| `date_extraction` | datetime.now() |

Le fichier CSV est encodé en **UTF-8 BOM** (compatible Excel France).

## Crédits Lusha

- Recherche : débité par résultat
- Email révélé : 1 crédit
- Téléphone révélé : 10 crédits

L'agent ne révèle que les contacts dont `canReveal` contient le champ demandé.

## Gestion des erreurs

- Lusha 429 → attente 60 s, 1 réessai
- BoondManager 401 → arrêt immédiat avec message
- BoondManager 429 → attente 30 s, 1 réessai
- Champ manquant → laissé vide, pas de plantage
