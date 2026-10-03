import os
import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request

load_dotenv()  # lit le fichier .env

app = Flask(__name__)

API_KEY = os.environ.get("BRAWL_API_KEY")
BASE_URL = os.environ.get("BRAWL_API_URL", "https://bsproxy.royaleapi.dev/v1")

TIER_LIST = {
    "S": ["Brawler 1", "Brawler 2"],
    "A": ["Brawler 3", "Brawler 4", "Brawler 5"],
    "B": ["Brawler 6", "Brawler 7"],
    "C": ["Brawler 8"],
    "D": ["Brawler 9"],
}

CARACTERES_TAG = set("0289PYLQGRJCUV")


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


@app.route("/")
def accueil():
    return render_template("index.html")


@app.route("/tierlist")
def tierlist():
    return render_template("tierlist.html", tiers=TIER_LIST)


@app.route("/joueur")
def joueur():
    texte = request.args.get("tag", "")
    if not texte:
        return render_template("joueur.html", joueur=None, erreur=None, tag="")

    tag = nettoyer_tag(texte)
    if tag is None:
        return render_template("joueur.html", joueur=None, tag=texte,
                               erreur="Tag invalide. Il ressemble à #2PP0Q8, sans caractère étrange.")

    donnees, erreur = appeler_api("/players/%23" + tag)
    if donnees:
        donnees["brawlers"].sort(key=lambda b: b["trophies"], reverse=True)
    return render_template("joueur.html", joueur=donnees, erreur=erreur, tag=tag)


if __name__ == "__main__":
    app.run(debug=True)