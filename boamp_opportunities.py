"""
Meet My Mama - Détection d'opportunités traiteur via le BOAMP (Île-de-France)
=============================================================================

Source : API Opendatasoft du BOAMP (DILA), données publiques, sans clé.
Sortie :
  - output/opportunites_boamp.csv     : avis ouverts, scorés et classés
  - output/attributions_boamp.csv     : marchés déjà attribués (signal de renouvellement)
  - output/rejets_boamp.csv           : avis écartés + raison (pour auditer les filtres)
  - output/qa_report.txt              : contrôles qualité
  - output/llm_checks.csv             : (option --llm) extraction IA + vérification anti-hallucination

Usage :
  pip install -r requirements.txt
  python boamp_opportunities.py                 # règles seules
  python boamp_opportunities.py --since-days 180
  python boamp_opportunities.py --llm           # + contrôle par LLM (ANTHROPIC_API_KEY requis)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

API = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records"
IDF_DEPTS = {"75", "77", "78", "91", "92", "93", "94", "95"}
OUT = Path(__file__).parent / "output"

# Requêtes plein texte envoyées à l'API (rappel large, le tri fin est fait localement)
SEARCH_TERMS = [
    "traiteur",
    "cocktail",
    "buffet",
    "plateaux repas",
    "pause café",
    "prestations de restauration",
    "restauration événementielle",
    "séminaire restauration",
    "banquet",
    "repas des seniors",
    "repas des aînés",
    "cérémonie",
    "dîner",
    "cocktail déjeunatoire",
]

# --------------------------------------------------------------------------- #
# Règles métier (volontairement lisibles : c'est la "logique de scoring")      #
# --------------------------------------------------------------------------- #
STRONG = {  # le besoin correspond au cœur de métier d'un traiteur événementiel
    "traiteur": 3, "cocktail": 3, "buffet": 2.5, "plateaux repas": 2.5, "plateau repas": 2.5,
    "pause cafe": 2, "pauses cafe": 2, "petit dejeuner": 1.5, "petits dejeuners": 1.5,
    "reception": 2, "receptions": 2, "evenement": 1.5, "evenementiel": 2, "evenementielle": 2,
    "seminaire": 1.5, "seminaires": 1.5, "inauguration": 2, "voeux": 2, "gala": 2,
    "vin d'honneur": 2.5, "dejeuner de travail": 2, "colloque": 1.5, "convivialite": 1.5,
    "banquet": 2.5, "repas des aines": 2.5, "repas des seniors": 2.5, "repas des anciens": 2.5,
    "ceremonie": 1.5, "diner": 1.5, "dejeunatoire": 2.5, "dinatoire": 2.5, "lunch": 2, "gouter": 1,
}
EXCLUDE = {  # faux positifs fréquents : restauration collective, fournitures, travaux...
    "restauration scolaire": "restauration collective", "restauration collective": "restauration collective",
    "cantine": "restauration collective", "portage de repas": "portage de repas",
    "denrees alimentaires": "fourniture de denrées", "fourniture de denrees": "fourniture de denrées",
    "liaison froide": "restauration collective", "liaison chaude": "restauration collective",
    "creche": "petite enfance", "ehpad": "médico-social", "centre hospitalier": "hospitalier",
    "equipement de cuisine": "équipement", "equipements de cuisine": "équipement",
    "travaux": "travaux", "nettoyage": "nettoyage", "distributeurs automatiques": "distribution automatique",
    "restaurant administratif": "restauration collective", "restaurant d'entreprise": "restauration collective",
    "gestion du restaurant": "restauration collective",
    "maitrise d'oeuvre": "travaux", "amenagement": "travaux", "rehabilitation": "travaux",
    "photocopieur": "hors sujet", "services d'assurance": "hors sujet",
}
# Mots ambigus : "réception" = accusé de réception / réception des travaux (constat run 1).
# Ils ne comptent que s'ils sont dans l'OBJET de l'avis, jamais dans le texte intégral.
AMBIGUOUS = {"reception", "receptions", "evenement", "seminaire", "seminaires", "colloque", "convivialite"}
SOCIAL_BONUS = {  # le positionnement "traiteur engagé" devient un avantage concurrentiel
    "marche reserve": 3, "l2113-12": 3, "l2113-13": 3, "l. 2113-12": 3, "l. 2113-13": 3,
    "economie sociale et solidaire": 2, "ess": 1, "insertion": 1.5, "clause sociale": 1.5,
    "clauses sociales": 1.5, "developpement durable": 0.5, "circuit court": 0.5,
    "circuits courts": 0.5, "anti-gaspillage": 0.5, "zero dechet": 0.5,
}
CPV_CATERING = {"55520000": 3, "55521000": 2, "55521200": 2, "55523000": 2,
                "55120000": 1, "55300000": 1, "55310000": 1, "79952000": 1, "79952100": 1}
CPV_COLLECTIVE = {"55524000", "55523100", "55512000", "15000000", "15800000", "55510000"}

BUYER_TYPES = [  # (motif, catégorie, multiplicateur d'accessibilité)
    (r"chambres? d.agriculture|chambre de commerce|cci ", "Chambre consulaire", 1.00),
    (r"universit|ecole|institut|cnrs|inria|inserm|campus|academie", "Enseignement / recherche / académies", 1.10),
    (r"musee|theatre|opera|philharmon|centre des monuments|bibliotheque|\bculture", "Culture", 1.10),
    (r"ministere|prefecture|agence|autorite|caisse|urssaf|cnav|cpam|france travail", "État / agence", 1.00),
    (r"region|departement|conseil departemental|communaute|metropole|grand paris|etablissement public territorial", "Collectivité (grande)", 1.00),
    (r"\bville d|commune|mairie|ccas|centre communal", "Commune / CCAS", 0.95),
    (r"sncf|ratp|edf|la poste|aeroports|eau de paris|epic|\bsa\b|\bsas\b", "Entreprise / régie publique", 1.05),
    (r"hopita|aphp|ap-hp|sante|chu", "Santé", 0.85),
]


def norm(s: str) -> str:
    s = str(s or "").replace("œ", "oe").replace("Œ", "oe").replace("æ", "ae")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.lower())


# --------------------------------------------------------------------------- #
# Extraction                                                                   #
# --------------------------------------------------------------------------- #
def fetch(term: str, since: str, session: requests.Session) -> list[dict]:
    records, offset, limit = [], 0, 100
    where_variants = [
        f'search("{term}") AND dateparution >= date\'{since}\'',
        f'search("{term}")',  # repli si la syntaxe de date est refusée
    ]
    for where in where_variants:
        records, offset, ok = [], 0, True
        while True:
            params = {"where": where, "limit": limit, "offset": offset, "order_by": "dateparution desc"}
            r = session.get(API, params=params, timeout=60)
            if r.status_code != 200:
                print(f"  ! API {r.status_code} pour '{term}' : {r.text[:200]}", file=sys.stderr)
                ok = False
                break
            batch = r.json().get("results", [])
            records.extend(batch)
            if len(batch) < limit or offset + limit >= 9900:
                break
            # sans filtre de date, on s'arrête dès qu'on sort de la fenêtre
            if "date'" not in where and batch and str(batch[-1].get("dateparution", "")) < since:
                break
            offset += limit
            time.sleep(0.2)
        if ok:
            return records
    return records


def as_list(x) -> list[str]:
    if x is None:
        return []
    if isinstance(x, list):
        return [str(i) for i in x]
    return [s.strip() for s in str(x).split(",") if s.strip()]


def walk(obj, path=""):
    """Parcourt récursivement le JSON 'donnees' (structures BOAMP hétérogènes)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v, path)
    else:
        yield path, obj


def parse_donnees(raw) -> dict:
    out = {"full_text": "", "cpv": set(), "valeur_estimee": None, "valeur_source": None, "deadline_donnees": None}
    if not raw:
        return out
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        out["full_text"] = str(raw)
        return out
    texts, values = [], []
    for path, val in walk(data):
        sval = str(val)
        if isinstance(val, str) and len(val) > 2:
            texts.append(val)
        if out["deadline_donnees"] is None and re.search(r"limite|deadline|receipt", path, re.I) \
                and re.match(r"\d{4}-\d{2}-\d{2}", sval):
            out["deadline_donnees"] = sval
        if re.search(r"cpv", path, re.I):
            out["cpv"].update(re.findall(r"\b(\d{8})\b", sval))
        if re.search(r"valeur|montant|amount", path, re.I):
            num = re.sub(r"[^\d.,]", "", sval).replace(",", ".")
            try:
                f = float(num) if num.count(".") <= 1 else None
                if f and 1_000 <= f <= 500_000_000:
                    values.append((f, path))
            except ValueError:
                pass
    out["full_text"] = " ".join(texts)
    out["cpv"].update(re.findall(r"\b(55\d{6}|79952\d{3}|15\d{6})\b", out["full_text"]))
    if values:  # on garde la plus grande valeur trouvée (souvent le montant global HT)
        v, p = max(values)
        out["valeur_estimee"], out["valeur_source"] = v, p
    return out


# --------------------------------------------------------------------------- #
# Scoring                                                                      #
# --------------------------------------------------------------------------- #
def classify_buyer(name: str) -> tuple[str, float]:
    n = norm(name)
    for pattern, label, mult in BUYER_TYPES:
        if re.search(pattern, n):
            return label, mult
    return "Autre", 1.0


def has(term: str, text: str) -> bool:
    """Mot ou expression entière, pluriel en -s/-x toléré."""
    return re.search(rf"\b{re.escape(term)}[sx]?\b", text) is not None


def score_row(row: pd.Series, today: datetime) -> dict:
    objet = norm(row["objet"])
    full = norm(row["objet"] + " " + row["full_text"])

    # 1) Adéquation au métier (objet pèse double : c'est ce que l'acheteur achète vraiment)
    obj_hits = {k: w for k, w in STRONG.items() if has(k, objet)}
    txt_hits = {k: w for k, w in STRONG.items() if k not in obj_hits and k not in AMBIGUOUS and has(k, full)}
    cpv_hits = {c: w for c, w in CPV_CATERING.items() if c in row["cpv"]}
    fit = 2 * sum(obj_hits.values()) + 0.5 * sum(txt_hits.values()) + sum(cpv_hits.values())
    explicit = bool(obj_hits.keys() - AMBIGUOUS) or any(c in cpv_hits for c in ("55520000", "55521000", "55523000"))
    fit_hits = {**obj_hits, **txt_hits}
    excl = sorted({lbl for k, lbl in EXCLUDE.items() if has(k, objet)})
    collective_cpv = bool(set(row["cpv"]) & CPV_COLLECTIVE) and not any(c in row["cpv"] for c in ("55520000", "55521000"))

    # 2) Avantage "traiteur engagé"
    social_hits = [k for k in SOCIAL_BONUS if has(k, full)]
    social = sum(SOCIAL_BONUS[k] for k in social_hits)

    # 3) Accessibilité pour une petite structure
    proc = norm(row.get("procedure", ""))
    access = 1.0
    if "adapt" in proc:
        access *= 1.15  # MAPA : dossier plus léger, souvent moins de concurrents
    elif "ouvert" in proc:
        access *= 0.90
    val = row.get("valeur_estimee")
    if pd.notna(val):
        if val <= 40_000: access *= 1.15
        elif val <= 215_000: access *= 1.05
        elif val > 1_000_000: access *= 0.70  # capacité de production et références exigées
    buyer_type, buyer_mult = classify_buyer(row["acheteur"])
    access *= buyer_mult

    # Probabilité de conversion : score relatif 0-100 (PAS une probabilité calibrée)
    raw = min(fit, 12) / 12 * 70 + min(social, 6) / 6 * 30
    proba = max(0.0, min(100.0, raw * access))
    if excl or collective_cpv:
        proba *= 0.25
    if not explicit:  # aucun besoin traiteur explicite (objet ou CPV) : on ne garde pas
        proba = 0.0

    # Urgence : fenêtre de réponse. Trop court = pas le temps de faire une bonne offre.
    dl = row["deadline"]
    days = (dl - today).days if pd.notna(dl) else None
    if days is None:
        urg = 40
    elif days > 180:  # système d'acquisition dynamique / candidature permanente
        urg = 60
    elif days < 3:
        urg = 20
    elif days <= 21:
        urg = 100 - (days - 3) * 1.5
    elif days <= 45:
        urg = 70 - (days - 21)
    else:
        urg = 40

    # multiplicatif : l'urgence module la priorité mais ne peut pas faire remonter un avis hors cible
    priority = proba * (0.5 + 0.5 * urg / 100)
    return {
        "fit_raw": round(fit, 1), "mots_cles": ", ".join(fit_hits), "mots_cles_objet": ", ".join(obj_hits),
        "cpv_traiteur": ", ".join(cpv_hits), "besoin_explicite": explicit, "bonus_social": ", ".join(social_hits),
        "exclusions": ", ".join(excl) + (" ; CPV restauration collective" if collective_cpv else ""),
        "type_acheteur": buyer_type, "jours_restants": days,
        "score_conversion": round(proba, 1), "score_urgence": round(urg, 1), "priorite": round(priority, 1),
    }


# --------------------------------------------------------------------------- #
# Option IA : extraction structurée + vérification anti-hallucination          #
# --------------------------------------------------------------------------- #
LLM_PROMPT = """Tu analyses un avis de marché public pour un traiteur événementiel d'entreprise.
Réponds UNIQUEMENT en JSON avec les clés :
- "type_besoin": "traiteur_evenementiel" | "restauration_collective" | "autre"
- "evenements": liste courte des événements cités (ex: "voeux", "cocktail"), [] si aucun
- "nb_convives": nombre ou null si non indiqué
- "date_evenement": date ISO ou null si non indiquée
- "citation": phrase COPIÉE MOT POUR MOT de l'avis qui justifie type_besoin
N'invente rien : si l'information n'est pas dans le texte, mets null.

Avis :
"""


def llm_check(df: pd.DataFrame, top_n: int = 40) -> pd.DataFrame:
    try:
        import anthropic
    except ImportError:
        print("  ! pip install anthropic pour utiliser --llm", file=sys.stderr)
        return pd.DataFrame()
    client = anthropic.Anthropic()
    rows = []
    for _, r in df.head(top_n).iterrows():
        text = (r["objet"] + "\n" + r["full_text"])[:6000]
        try:
            msg = client.messages.create(model=os.getenv("LLM_MODEL", "claude-haiku-5-5"), max_tokens=400,
                                         messages=[{"role": "user", "content": LLM_PROMPT + text}])
            content = msg.content[0].text
            js = json.loads(content[content.find("{"): content.rfind("}") + 1])
        except Exception as e:  # noqa: BLE001
            rows.append({"idweb": r["idweb"], "llm_erreur": str(e)[:200]})
            continue
        citation = norm(js.get("citation") or "")
        source = norm(text)
        nb = js.get("nb_convives")
        rows.append({
            "idweb": r["idweb"],
            "llm_type_besoin": js.get("type_besoin"),
            "llm_evenements": ", ".join(js.get("evenements") or []),
            "llm_nb_convives": nb,
            "llm_date_evenement": js.get("date_evenement"),
            "llm_citation": js.get("citation"),
            # Contrôles : la citation existe-t-elle vraiment ? le nombre apparaît-il dans le texte ?
            "check_citation_trouvee": bool(citation) and citation[:120] in source,
            "check_nb_convives_trouve": (nb is None) or (str(nb) in text),
            "desaccord_regles": (js.get("type_besoin") != "traiteur_evenementiel") == (r["score_conversion"] >= 30),
        })
        time.sleep(0.3)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Pipeline                                                                     #
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-days", type=int, default=180)
    ap.add_argument("--llm", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc)
    since = (today - timedelta(days=args.since_days)).strftime("%Y-%m-%d")
    qa = [f"Exécution : {today:%Y-%m-%d %H:%M} UTC | fenêtre de parution depuis {since}"]

    session = requests.Session()
    raw = []
    for term in SEARCH_TERMS:
        recs = fetch(term, since, session)
        print(f"  '{term}' : {len(recs)} avis")
        qa.append(f"Requête '{term}' : {len(recs)} avis bruts")
        for rec in recs:
            rec["_terme"] = term
        raw.extend(recs)
    if not raw:
        sys.exit("Aucun résultat : vérifier la connexion ou l'API.")

    rows = []
    for rec in raw:
        d = parse_donnees(rec.get("donnees"))
        rows.append({
            "idweb": rec.get("idweb") or rec.get("id"),
            "objet": rec.get("objet") or "",
            "acheteur": rec.get("nomacheteur") or "",
            "departements": as_list(rec.get("code_departement")),
            "date_parution": rec.get("dateparution"),
            "deadline_raw": rec.get("datelimitereponse"),
            "nature": rec.get("nature_libelle") or rec.get("nature") or "",
            "type_avis": rec.get("type_avis") or "",
            "procedure": rec.get("procedure_libelle") or rec.get("type_procedure") or "",
            "type_marche": rec.get("type_marche") or "",
            "descripteurs": ", ".join(as_list(rec.get("descripteur_libelle"))),
            "url": rec.get("url_avis") or f"https://www.boamp.fr/pages/avis/?q=idweb:{rec.get('idweb')}",
            "cpv": sorted(d["cpv"]), "valeur_estimee": d["valeur_estimee"],
            "valeur_source": d["valeur_source"], "deadline_donnees": d["deadline_donnees"], "full_text": d["full_text"], "terme": rec["_terme"],
        })
    df = pd.DataFrame(rows)

    # --- Contrôles qualité ------------------------------------------------- #
    n0 = len(df)
    df["termes_trouves"] = df.groupby("idweb")["terme"].transform(lambda s: ", ".join(sorted(set(s))))
    df = df.drop_duplicates("idweb")
    qa.append(f"Doublons inter-requêtes supprimés : {n0 - len(df)} (reste {len(df)})")

    # parsing élément par élément : les formats de date BOAMP varient (avec/sans heure, fuseau)
    df["deadline_raw"] = df["deadline_raw"].fillna(df["deadline_donnees"])
    df["deadline"] = df["deadline_raw"].apply(lambda x: pd.to_datetime(x, errors="coerce", utc=True))
    df["deadline"] = pd.to_datetime(df["deadline"], utc=True)
    # Un rectificatif sans date limite hérite de la date de son avis d'origine (même acheteur et objet).
    # Constat run 2 : le rectificatif de Paris-Saclay restait "ouvert" alors que l'original avait expiré.
    df["_key"] = df["acheteur"].map(norm) + "|" + df["objet"].map(norm).str[:80]
    known = df.dropna(subset=["deadline"]).groupby("_key")["deadline"].max()
    rectif = df["deadline"].isna() & df["nature"].map(norm).str.contains("rectificatif")
    df.loc[rectif, "deadline"] = df.loc[rectif, "_key"].map(known)
    qa.append(f"Rectificatifs sans date : {int(rectif.sum())}, dont {int(df.loc[rectif, 'deadline'].notna().sum())} "
              "datés grâce à l'avis d'origine")
    qa.append(f"Date limite absente ou illisible : {df['deadline'].isna().sum()}")
    # Avis multi-départements : "75" figure souvent dans la liste d'avis nationaux (constat run 1 :
    # CPAM Maine-et-Loire, CH d'Arras...). On exige que la majorité des départements soient franciliens.
    df["idf"] = df["departements"].apply(lambda ds: len(ds) > 0 and sum(d in IDF_DEPTS for d in ds) / len(ds) > 0.5)
    qa.append(f"Sans département renseigné : {(df['departements'].str.len() == 0).sum()}")

    rejets = []
    def reject(mask, reason):
        nonlocal df
        r = df[mask].copy(); r["raison_rejet"] = reason; rejets.append(r)
        df = df[~mask]
        qa.append(f"Rejet - {reason} : {int(mask.sum())}")

    reject(~df["idf"], "hors Île-de-France")
    nat = df["nature"].map(norm) + " " + df["type_avis"].map(norm)
    attrib_mask = nat.str.contains("attribution|resultat")
    attributions = df[attrib_mask].copy()
    df = df[~attrib_mask]
    qa.append(f"Avis d'attribution mis de côté (signal de renouvellement) : {len(attributions)}")
    expired = df[df["deadline"].notna() & (df["deadline"] < today)].copy()
    reject(df["deadline"].notna() & (df["deadline"] < today), "date limite dépassée")

    # Rectificatifs : on garde l'avis le plus récent par (acheteur, objet)
    n1 = len(df)
    df = df.sort_values("date_parution").drop_duplicates("_key", keep="last")
    qa.append(f"Rectificatifs / republications fusionnés : {n1 - len(df)}")

    # --- Scoring ----------------------------------------------------------- #
    if df.empty:
        print("\n".join(qa))
        sys.exit("Aucun avis ouvert en IDF après filtres : augmenter --since-days.")
    scores = df.apply(lambda r: pd.Series(score_row(r, today)), axis=1)
    df = pd.concat([df, scores], axis=1)
    reject(df["score_conversion"] < 10, "hors cible (pas de besoin traiteur explicite ou score < 10)")
    df = df.sort_values(["priorite", "score_conversion"], ascending=False)

    qa.append(f"Valeur estimée trouvée pour {df['valeur_estimee'].notna().sum()}/{len(df)} avis (extraction heuristique, à vérifier)")
    qa.append(f"Avis avec exclusion (restauration collective, etc.) conservés mais pénalisés : {(df['exclusions'] != '').sum()}")
    qa.append(f"OPPORTUNITÉS FINALES : {len(df)}")

    cols = ["priorite", "score_conversion", "score_urgence", "jours_restants", "deadline", "acheteur",
            "type_acheteur", "objet", "procedure", "valeur_estimee", "departements", "cpv", "mots_cles",
            "bonus_social", "exclusions", "mots_cles_objet", "cpv_traiteur", "nature", "type_avis",
            "date_parution", "idweb", "url", "termes_trouves"]
    def statut(r):
        if pd.isna(r["deadline"]):
            if "rectificatif" in norm(r["nature"]):
                return "à vérifier : rectificatif sans date (avis d'origine introuvable)"
            if re.search(r"negociee|restreinte|nc", norm(r["procedure"])):
                return "à vérifier : pas de date limite, phase de candidature peut-être close"
            return "à vérifier : pas de date limite"
        if r["jours_restants"] is not None and r["jours_restants"] > 180:
            return "à vérifier : candidature permanente probable (SAD)"
        if r["jours_restants"] is not None and r["jours_restants"] < 3:
            return "ouvert, délai très court"
        return "ouvert"
    df["statut"] = df.apply(statut, axis=1)
    df["verif_manuelle"] = ""  # à remplir : OK / faux positif / déjà clos...
    df[["statut"] + cols + ["verif_manuelle"]].to_csv(OUT / "opportunites_boamp.csv", index=False, encoding="utf-8-sig")
    attributions[["acheteur", "objet", "date_parution", "departements", "valeur_estimee", "idweb", "url"]] \
        .to_csv(OUT / "attributions_boamp.csv", index=False, encoding="utf-8-sig")
    if rejets:
        pd.concat(rejets)[["raison_rejet", "acheteur", "objet", "departements", "deadline_raw", "idweb", "url"]] \
            .to_csv(OUT / "rejets_boamp.csv", index=False, encoding="utf-8-sig")

    # Acheteurs récurrents : ils ont déjà acheté du traiteur (consultation close ou attribuée).
    # Utile car, depuis le 01/04/2026, un acheteur public peut commander sans publicité ni mise en
    # concurrence sous 60 000 EUR HT (art. R2122-8 CCP) : ce sont des cibles de prospection directe.
    hist = pd.concat([expired.assign(source="consultation close"), attributions.assign(source="attribution")])
    if not hist.empty:
        hs = hist.apply(lambda r: pd.Series(score_row(r, today)), axis=1)
        hist = hist.drop(columns=[c for c in hs.columns if c in hist.columns]).join(hs)
        hist = hist[hist["besoin_explicite"] & (hist["score_conversion"] >= 10) & ~hist["acheteur"].isin(df["acheteur"])]
        rec = (hist.groupby("acheteur").agg(nb_avis=("idweb", "nunique"), derniere_parution=("date_parution", "max"),
                                            sources=("source", lambda x: ", ".join(sorted(set(x)))),
                                            objet_exemple=("objet", "first"), url=("url", "first"))
               .sort_values(["nb_avis", "derniere_parution"], ascending=False))
        rec.to_csv(OUT / "acheteurs_recurrents.csv", encoding="utf-8-sig")
        qa.append(f"Acheteurs récurrents (traiteur déjà acheté, hors opportunités ouvertes) : {len(rec)}")

    if args.llm:
        if not os.getenv("ANTHROPIC_API_KEY"):
            qa.append("LLM : ignoré (ANTHROPIC_API_KEY absente)")
        else:
            chk = llm_check(df)
            if not chk.empty:
                chk.to_csv(OUT / "llm_checks.csv", index=False, encoding="utf-8-sig")
                qa.append(f"LLM : {len(chk)} avis analysés | citations introuvables dans la source : "
                          f"{(~chk.get('check_citation_trouvee', pd.Series(dtype=bool)).fillna(False)).sum()} | "
                          f"nb de convives non retrouvé : {(~chk.get('check_nb_convives_trouve', pd.Series(dtype=bool)).fillna(True)).sum()} | "
                          f"désaccords avec les règles : {chk.get('desaccord_regles', pd.Series(dtype=bool)).fillna(False).sum()}")

    (OUT / "qa_report.txt").write_text("\n".join(qa), encoding="utf-8")
    print("\n".join(qa))
    print(f"\nTop 10 :\n{df[['priorite', 'jours_restants', 'acheteur', 'objet']].head(10).to_string(index=False)}")


if __name__ == "__main__":
    main()
