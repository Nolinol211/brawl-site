import os
import re
import time
from datetime import datetime, timezone
from string import capwords

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for

load_dotenv()  # lit le fichier .env

app = Flask(__name__)

API_KEY = os.environ.get("BRAWL_API_KEY")
BASE_URL = os.environ.get("BRAWL_API_URL", "https://bsproxy.royaleapi.dev/v1")

CARACTERES_TAG = set("0289PYLQGRJCUV")
NIVEAU_MAX = 11  # niveau de puissance maximum d'un brawler

# (trophées minimum, titre, emoji) : modifie les titres et les seuils comme tu veux !
TITRES_TROPHEES = [
    (0, "Larve de Cactus", "🌵"),
    (5000, "Casseur de Caisses", "📦"),
    (15000, "Mascotte du Quartier", "🧸"),
    (30000, "Terreur de la Pelouse", "🌿"),
    (50000, "Chasseur de Gemmes", "💎"),
    (75000, "Boss du Showdown", "💀"),
    (100000, "Légende du Dash", "⚡"),
    (130000, "Dieu des Étoiles", "⭐"),
]

# (pourcentage de victoires minimum, titre, emoji)
TITRES_VICTOIRES = [
    (80, "Machine à gagner", "🤖"),
    (65, "Gros bras", "💪"),
    (50, "Ni chaud ni froid", "⚖️"),
    (35, "Apprenti en formation", "🎓"),
    (0, "Pigeon professionnel", "🐦"),
]

# Titres selon les trophées gagnés sur 7 jours : (trophées minimum, titre, emoji)
# L'API ne donne que les 25 derniers combats, donc les seuils sont réglés pour ça.
TITRES_SEMAINE = [
    (-9999, "En chute libre", "🪂"),
    (-39, "Pas ta semaine", "🌧️"),
    (0, "Sur place", "🧍"),
    (1, "Joueur du dimanche", "☕"),
    (30, "Régulier tranquille", "🙂"),
    (70, "Grimpeur motivé", "🧗"),
    (110, "Gros puant", "🦨"),
    (150, "Ne dort jamais", "😵"),
    (200, "Le Try Harder suprême", "👑"),
]
TITRE_INACTIF = ("Inactif total", "💤")

LIBELLES = {
    "victory": ("VICTOIRE", "🏆"),
    "defeat": ("DÉFAITE", "💥"),
    "draw": ("ÉGALITÉ", "🤝"),
}


# ---------- Outils ----------
def nettoyer_tag(texte):
    """'#2pp' ou '2pp' -> '2PP'. Renvoie None si le tag est impossible."""
    tag = texte.strip().upper().replace("#", "").replace("O", "0")
    if not tag or not set(tag) <= CARACTERES_TAG:
        return None
    return tag


def appeler_api(chemin):
    """Renvoie (donnees, erreur). Une des deux valeurs vaut None."""
    if not API_KEY:
        return None, "Clé API manquante : vérifie ton fichier .env."
    try:
        reponse = requests.get(
            BASE_URL + chemin,
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=10,
        )
    except requests.RequestException:
        return None, "Impossible de contacter l'API Brawl Stars."

    if reponse.status_code == 200:
        return reponse.json(), None
    messages = {
        403: "Clé refusée : vérifie la clé et l'IP autorisée (45.79.218.79).",
        404: "Joueur introuvable : vérifie le tag.",
        429: "Trop de requêtes, réessaie dans un instant.",
        503: "L'API est en maintenance.",
    }
    return None, messages.get(reponse.status_code, f"Erreur de l'API ({reponse.status_code}).")


def nom_mode(code):
    """'gemGrab' -> 'Gem Grab'."""
    if not code:
        return "Mode inconnu"
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", code).replace("_", " ").title()


def age_secondes(texte):
    """'20261004T143000.000Z' -> nombre de secondes écoulées (None si illisible)."""
    try:
        moment = datetime.strptime(texte, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return int((datetime.now(timezone.utc) - moment).total_seconds())


def duree(secondes):
    """3700 -> '1 h', 200000 -> '2 j'."""
    if secondes < 3600:
        return f"{max(1, secondes // 60)} min"
    if secondes < 86400:
        return f"{secondes // 3600} h"
    return f"{secondes // 86400} j"


def ilya(texte):
    secondes = age_secondes(texte)
    return "" if secondes is None else "il y a " + duree(secondes)


# ---------- Grades rigolos ----------
def grade_trophees(trophees):
    index = 0
    for i, (seuil, _, _) in enumerate(TITRES_TROPHEES):
        if trophees >= seuil:
            index = i
    seuil, nom, emoji = TITRES_TROPHEES[index]
    grade = {"nom": nom, "emoji": emoji, "suivant": None, "restants": 0, "pourcent": 100}
    if index + 1 < len(TITRES_TROPHEES):
        seuil_suivant, nom_suivant, _ = TITRES_TROPHEES[index + 1]
        grade["suivant"] = nom_suivant
        grade["restants"] = seuil_suivant - trophees
        grade["pourcent"] = round((trophees - seuil) / (seuil_suivant - seuil) * 100)
    return grade


def grade_victoires(taux):
    for seuil, nom, emoji in TITRES_VICTOIRES:
        if taux >= seuil:
            return {"nom": nom, "emoji": emoji}
    return {"nom": TITRES_VICTOIRES[-1][1], "emoji": TITRES_VICTOIRES[-1][2]}


def titre_semaine(gain, nb_combats):
    """Titre rigolo selon les trophées gagnés sur 7 jours."""
    if nb_combats == 0:
        return {"nom": TITRE_INACTIF[0], "emoji": TITRE_INACTIF[1]}
    choisi = TITRES_SEMAINE[0]
    for ligne in TITRES_SEMAINE:
        if gain >= ligne[0]:
            choisi = ligne
    return {"nom": choisi[1], "emoji": choisi[2]}


# ---------- Analyse des données ----------
def enrichir_profil(profil):
    brawlers = profil.get("brawlers", [])
    brawlers.sort(key=lambda b: b["trophies"], reverse=True)
    profil["brawlers"] = brawlers
    nombre = len(brawlers)
    profil["moyenne"] = round(profil["trophies"] / nombre) if nombre else 0
    profil["niveau_max"] = sum(1 for b in brawlers if b["power"] >= NIVEAU_MAX)
    profil["meilleur_record"] = max(brawlers, key=lambda b: b["highestTrophies"]) if nombre else None
    profil["max_trophees"] = max(1, brawlers[0]["trophies"]) if nombre else 1


def analyser_combats(items, tag):
    ma_tag = "#" + tag
    combats = []
    for item in items:
        bataille = item.get("battle", {})
        evenement = item.get("event", {})

        joueurs = [p for equipe in bataille.get("teams", []) for p in equipe]
        joueurs += bataille.get("players", [])
        brawler = "?"
        for p in joueurs:
            if p.get("tag") == ma_tag:
                choisi = p.get("brawler") or (p.get("brawlers") or [{}])[0]
                brawler = choisi.get("name", "?")
                break

        resultat = bataille.get("result")
        rang = bataille.get("rank")
        if resultat in LIBELLES:
            libelle, emoji = LIBELLES[resultat]
        elif rang is not None:
            # Showdown : pas de victoire/défaite mais un classement (la 1re place s'affiche en vert)
            resultat, libelle = "classement", f"RANG {rang}"
            emoji = "🥇" if rang == 1 else "🏅"
        else:
            resultat, libelle, emoji = "inconnu", "?", "❔"
        classe = "premier" if (resultat == "classement" and rang == 1) else resultat

        age = age_secondes(item.get("battleTime"))
        combats.append({
            "mode": nom_mode(bataille.get("mode") or evenement.get("mode")),
            "map": evenement.get("map") or "Map inconnue",
            "resultat": resultat,
            "classe": classe,
            "libelle": libelle,
            "emoji": emoji,
            "trophees": bataille.get("trophyChange", 0),
            "brawler": brawler.title(),
            "quand": ilya(item.get("battleTime")),
            "age": age,
        })

    victoires = sum(1 for c in combats if c["resultat"] == "victory")
    defaites = sum(1 for c in combats if c["resultat"] == "defeat")
    egalites = sum(1 for c in combats if c["resultat"] == "draw")
    total = victoires + defaites + egalites
    decisifs = victoires + defaites
    taux = round(victoires / decisifs * 100) if decisifs else 0

    # Série en cours (les plus récents d'abord)
    serie = {"type": None, "nb": 0}
    for c in combats:
        if c["resultat"] not in ("victory", "defeat"):
            continue
        if serie["type"] is None:
            serie["type"] = c["resultat"]
        if c["resultat"] == serie["type"]:
            serie["nb"] += 1
        else:
            break

    # Trophées pris sur les 7 derniers jours (parmi les combats que l'API donne)
    sept_jours = 7 * 86400
    semaine_combats = [c for c in combats if c["age"] is not None and c["age"] <= sept_jours]
    gain_semaine = sum(c["trophees"] for c in semaine_combats)
    ages = [c["age"] for c in combats if c["age"] is not None]
    plus_ancien = max(ages) if ages else 0
    # Si les combats donnés par l'API ne remontent pas jusqu'à 7 jours, le vrai total peut être plus grand
    tronque = len(combats) >= 25 and plus_ancien < sept_jours

    # Stats par brawler
    par = {}
    for c in combats:
        if c["resultat"] in ("victory", "defeat"):
            ligne = par.setdefault(c["brawler"], {"nom": c["brawler"], "parties": 0, "victoires": 0})
            ligne["parties"] += 1
            ligne["victoires"] += c["resultat"] == "victory"
    par_brawler = sorted(par.values(), key=lambda x: x["parties"], reverse=True)
    for ligne in par_brawler:
        ligne["taux"] = round(ligne["victoires"] / ligne["parties"] * 100)
    candidats = [x for x in par_brawler if x["parties"] >= 2]
    meilleur = max(candidats, key=lambda x: (x["taux"], x["parties"])) if candidats else None

    return {
        "combats": combats,
        "total": total,
        "victoires": victoires,
        "defaites": defaites,
        "egalites": egalites,
        "taux": taux,
        "pct_v": round(victoires / total * 100, 1) if total else 0,
        "pct_d": round(defaites / total * 100, 1) if total else 0,
        "serie": serie,
        "semaine": gain_semaine,
        "nb_semaine": len(semaine_combats),
        "titre_semaine": titre_semaine(gain_semaine, len(semaine_combats)),
        "tronque": tronque,
        "couverture": duree(plus_ancien) if plus_ancien else "",
        "par_brawler": par_brawler[:6],
        "meilleur": meilleur,
        "grade": grade_victoires(taux),
    }


def construire_badges(profil, analyse):
    badges = []
    if analyse:
        serie = analyse["serie"]
        if serie["type"] == "victory" and serie["nb"] >= 3:
            badges.append(("🔥", f"En feu : {serie['nb']} victoires d'affilée"))
        elif serie["type"] == "defeat" and serie["nb"] >= 3:
            badges.append(("🌧️", f"Il pleut : {serie['nb']} défaites d'affilée"))
        gain = analyse["semaine"]
        if gain >= 40:
            badges.append(("📈", f"+{gain} trophées sur 7 jours, ça grimpe !"))
        elif gain <= -40:
            badges.append(("📉", f"{gain} trophées sur 7 jours, courage..."))
        if analyse["meilleur"]:
            badges.append(("👑", f"Brawler du moment : {analyse['meilleur']['nom']}"))
    if profil["niveau_max"]:
        n = profil["niveau_max"]
        badges.append(("💪", f"{n} brawler{'s' if n > 1 else ''} au niveau max"))
    record = profil["meilleur_record"]
    if record:
        badges.append(("🏅", f"Plus beau record : {record['name'].title()} ({record['highestTrophies']} 🏆)"))
    return badges


# ---------- Liste des brawlers (pour la tier list) ----------
BRAWLIFY_URL = "https://api.brawlapi.com/v1/brawlers"
IMAGE_PAR_DEFAUT = "https://cdn.brawlify.com/brawlers/borderless/{id}.png"
_cache_brawlers = {"heure": 0, "liste": []}


def charger_brawlers():
    """Liste de tous les brawlers du jeu avec leur icône. Mise en cache 6 h."""
    maintenant = time.time()
    if _cache_brawlers["liste"] and maintenant - _cache_brawlers["heure"] < 6 * 3600:
        return _cache_brawlers["liste"]

    # 1) Brawlify : noms propres et icônes (sans bordure). On ignore les brawlers pas encore sortis.
    brawlify = {}
    try:
        reponse = requests.get(BRAWLIFY_URL, timeout=10)
        if reponse.status_code == 200:
            for b in reponse.json().get("list", []):
                if b.get("released") is False:
                    continue
                image = b.get("imageUrl2") or b.get("imageUrl") or IMAGE_PAR_DEFAUT.format(id=b["id"])
                brawlify[b["id"]] = {"id": b["id"], "nom": b["name"], "image": image}
    except (requests.RequestException, ValueError, KeyError, AttributeError):
        brawlify = {}

    # 2) API officielle : la liste de référence des brawlers qui existent vraiment dans le jeu.
    #    Si elle répond, on la suit (et on complète avec Brawlify pour les noms et les images).
    liste = []
    officiel, _ = appeler_api("/brawlers")
    if officiel and officiel.get("items"):
        for b in officiel["items"]:
            liste.append(brawlify.get(b["id"]) or {
                "id": b["id"],
                "nom": capwords(b["name"]),
                "image": IMAGE_PAR_DEFAUT.format(id=b["id"]),
            })
    else:
        liste = list(brawlify.values())

    liste.sort(key=lambda b: b["nom"].lower())
    if liste:
        _cache_brawlers["liste"] = liste
        _cache_brawlers["heure"] = maintenant
    return liste


# ---------- Pages ----------
@app.route("/")
def accueil():
    return render_template("index.html", erreur=None, tag="")


@app.route("/tierlist")
def tierlist():
    return render_template("tierlist.html")


@app.route("/api/brawlers")
def api_brawlers():
    liste = charger_brawlers()
    if not liste:
        return jsonify({"erreur": "Liste des brawlers indisponible pour le moment."}), 503
    return jsonify({"brawlers": liste})


@app.route("/joueur")
def joueur():
    texte = request.args.get("tag", "")
    if not texte.strip():
        return redirect(url_for("accueil"))

    tag = nettoyer_tag(texte)
    if tag is None:
        return render_template("index.html", tag=texte,
                               erreur="Tag invalide. Il ressemble à #2PP0Q8, sans caractère étrange.")

    profil, erreur = appeler_api("/players/%23" + tag)
    if erreur:
        return render_template("index.html", tag=texte, erreur=erreur)
    enrichir_profil(profil)

    journal, _ = appeler_api("/players/%23" + tag + "/battlelog")
    analyse = analyser_combats(journal.get("items", []), tag) if journal else None

    return render_template(
        "joueur.html",
        joueur=profil,
        grade=grade_trophees(profil["trophies"]),
        analyse=analyse,
        badges=construire_badges(profil, analyse),
    )


if __name__ == "__main__":
    app.run(debug=True)