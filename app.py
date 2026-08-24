import os
import sqlite3
from functools import wraps

import requests
from flask import Flask, request, redirect, url_for, render_template_string, session

app = Flask(__name__)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "change-this-secret-key"
)

ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "").strip()
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "").strip()
ADMIN_KEY = os.environ.get("ADMIN_KEY", "").strip()

DB_FILE = "opportunites.db"

COUNTRIES = {
    "fr": "France",
    "gb": "Royaume-Uni",
    "ca": "Canada",
    "us": "États-Unis",
    "de": "Allemagne",
    "au": "Australie",
    "be": "Belgique",
    "ch": "Suisse",
    "it": "Italie",
    "es": "Espagne",
    "nl": "Pays-Bas",
    "ie": "Irlande",
    "at": "Autriche",
    "pl": "Pologne",
    "za": "Afrique du Sud",
    "in": "Inde",
    "br": "Brésil",
    "mx": "Mexique",
}

CATEGORIES = {
    "emploi": "Emploi",
    "bourse": "Bourse",
    "stage_remunere": "Stage rémunéré",
}


def db():
    connection = sqlite3.connect(DB_FILE, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    connection = db()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS offres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT UNIQUE,
            titre TEXT NOT NULL,
            entreprise TEXT,
            description TEXT,
            pays TEXT,
            localisation TEXT,
            categorie TEXT,
            salaire_min REAL,
            salaire_max REAL,
            devise TEXT,
            lien TEXT,
            date_publication TEXT,
            source TEXT DEFAULT 'Adzuna'
        )
    """)

    connection.commit()
    connection.close()


init_db()


def admin_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return function(*args, **kwargs)

    return wrapper


def is_paid_internship(text, salary_min=None, salary_max=None):
    text = (text or "").lower()

    if salary_min is not None or salary_max is not None:
        return True

    words = (
        "paid internship",
        "paid intern",
        "paid placement",
        "stipend",
        "salary",
        "salaried",
        "paid trainee",
        "rémunéré",
        "remunere",
        "rémunération",
        "remuneration",
        "payé",
        "paye",
    )

    return any(word in text for word in words)


def rechercher_adzuna(country, keyword="", page=1, remunerated=False):
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return []

    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "results_per_page": 20,
        "content-type": "application/json",
    }

    if keyword:
        params["what"] = keyword

    if remunerated:
        params["what"] = (
            f"{keyword} paid internship"
            if keyword
            else "paid internship"
        )

    url = (
        f"https://api.adzuna.com/v1/api/jobs/"
        f"{country}/search/{page}"
    )

    response = requests.get(
        url,
        params=params,
        timeout=20,
        headers={
            "Accept": "application/json",
            "User-Agent": "OpportunitesInternationales/1.0",
        },
    )

    response.raise_for_status()

    return response.json().get("results", [])


def enregistrer_offres(offres, country, categorie):
    connection = db()
    nombre = 0

    for offre in offres:
        source_id = str(offre.get("id", "")).strip()

        if not source_id:
            continue

        company = offre.get("company") or {}
        location = offre.get("location") or {}
        category = offre.get("category") or {}

        titre = str(offre.get("title", "") or "").strip()
        description = str(
            offre.get("description", "") or ""
        ).strip()

        entreprise = (
            company.get("display_name")
            or "Entreprise non précisée"
        )

        localisation = (
            location.get("display_name")
            or ""
        )

        salaire_min = offre.get("salary_min")
        salaire_max = offre.get("salary_max")

        lien = (
            offre.get("redirect_url")
            or ""
        )

        date_publication = (
            offre.get("created")
            or ""
        )

        texte = (
            titre
            + " "
            + description
            + " "
            + str(category.get("label", "") or "")
        ).lower()

        categorie_finale = categorie

        if (
            categorie == "Stage rémunéré"
            or is_paid_internship(
                texte,
                salaire_min,
                salaire_max
            )
        ):
            if any(
                word in texte
                for word in (
                    "internship",
                    "intern",
                    "trainee",
                    "stage",
                    "placement",
                    "rémun",
                    "remuner",
                    "paid",
                )
            ):
                categorie_finale = "Stage rémunéré"

        try:
            connection.execute("""
                INSERT INTO offres (
                    source_id,
                    titre,
                    entreprise,
                    description,
                    pays,
                    localisation,
                    categorie,
                    salaire_min,
                    salaire_max,
                    devise,
                    lien,
                    date_publication,
                    source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                source_id,
                titre,
                entreprise,
                description,
                COUNTRIES.get(country, country.upper()),
                localisation,
                categorie_finale,
                salaire_min,
                salaire_max,
                "",
                lien,
                date_publication,
                "Adzuna",
            ))

            nombre += 1

        except sqlite3.IntegrityError:
            pass

    connection.commit()
    connection.close()

    return nombre


@app.route("/")
def accueil():
    keyword = request.args.get("keyword", "").strip()
    country = request.args.get("country", "ca").strip()
    categorie = request.args.get("categorie", "emploi").strip()

    offres = []

    recherche = (
        request.args.get("search")
        or keyword
    )

    if recherche:
        remunerated = categorie == "stage_remunere"

        try:
            offres_api = rechercher_adzuna(
                country=country,
                keyword=keyword,
                page=1,
                remunerated=remunerated,
            )

            categorie_api = CATEGORIES.get(
                categorie,
                "Emploi"
            )

            enregistrer_offres(
                offres_api,
                country,
                categorie_api
            )

        except Exception as error:
            print("Erreur Adzuna:", error)

    connection = db()

    if categorie == "emploi":
        query = """
            SELECT *
            FROM offres
            WHERE categorie = 'Emploi'
               OR categorie IS NULL
            ORDER BY id DESC
            LIMIT 100
        """

    elif categorie == "bourse":
        query = """
            SELECT *
            FROM offres
            WHERE lower(categorie) IN
            ('bourse', 'bourses')
            ORDER BY id DESC
            LIMIT 100
        """

    elif categorie == "stage_remunere":
        query = """
            SELECT *
            FROM offres
            WHERE categorie = 'Stage rémunéré'
            ORDER BY id DESC
            LIMIT 100
        """

    else:
        query = """
            SELECT *
            FROM offres
            WHERE categorie IN
            ('Emploi', 'Bourse', 'Bourses',
             'Stage rémunéré')
            ORDER BY id DESC
            LIMIT 100
        """

    offres = connection.execute(query).fetchall()

    connection.close()

    return render_template_string(
        HTML_HOME,
        offres=offres,
        keyword=keyword,
        country=country,
        categorie=categorie,
        countries=COUNTRIES,
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    message = ""

    if request.method == "POST":
        key = request.form.get("key", "").strip()

        if ADMIN_KEY and key == ADMIN_KEY:
            session["admin"] = True
            return redirect(url_for("admin"))

        message = "Clé administrateur incorrecte."

    return render_template_string(
        HTML_LOGIN,
        message=message
    )


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("accueil"))


@app.route("/admin")
@admin_required
def admin():
    connection = db()

    offres = connection.execute("""
        SELECT *
        FROM offres
        ORDER BY id DESC
        LIMIT 200
    """).fetchall()

    connection.close()

    return render_template_string(
        HTML_ADMIN,
        offres=offres
    )


@app.route(
    "/admin/supprimer/<int:offre_id>",
    methods=["POST"]
)
@admin_required
def supprimer(offre_id):
    connection = db()

    connection.execute(
        "DELETE FROM offres WHERE id = ?",
        (offre_id,)
    )

    connection.commit()
    connection.close()

    return redirect(url_for("admin"))


@app.route(
    "/admin/modifier/<int:offre_id>",
    methods=["GET", "POST"]
)
@admin_required
def modifier(offre_id):
    connection = db()

    offre = connection.execute("""
        SELECT *
        FROM offres
        WHERE id = ?
    """, (offre_id,)).fetchone()

    if offre is None:
        connection.close()
        return redirect(url_for("admin"))

    if request.method == "POST":
        connection.execute("""
            UPDATE offres
            SET titre = ?,
                entreprise = ?,
                description = ?,
                pays = ?,
                localisation = ?,
                categorie = ?,
                lien = ?
            WHERE id = ?
        """, (
            request.form.get("titre", "").strip(),
            request.form.get("entreprise", "").strip(),
            request.form.get("description", "").strip(),
            request.form.get("pays", "").strip(),
            request.form.get("localisation", "").strip(),
            request.form.get("categorie", "Emploi").strip(),
            request.form.get("lien", "").strip(),
            offre_id,
        ))

        connection.commit()
        connection.close()

        return redirect(url_for("admin"))

    connection.close()

    return render_template_string(
        HTML_EDIT,
        offre=offre
    )


@app.route("/health")
def health():
    return "OK", 200


HTML_HOME = """
<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>Opportunités internationales</title>

<style>
body {
    font-family: Arial, sans-serif;
    background: #f4f6f8;
    margin: 0;
    padding: 20px;
}

.container {
    max-width: 1100px;
    margin: auto;
}

header,
.search,
.card {
    background: white;
    border-radius: 15px;
}

header {
    padding: 25px;
    margin-bottom: 20px;
}

.search {
    padding: 20px;
    margin-bottom: 20px;
}

input,
select,
button {
    padding: 12px;
    margin: 5px;
    border-radius: 8px;
    border: 1px solid #ccc;
}

button {
    cursor: pointer;
}

.card {
    padding: 20px;
    margin: 15px 0;
}

.admin {
    float: right;
}

a {
    text-decoration: none;
}
</style>
</head>

<body>

<div class="container">

<header>

<a class="admin" href="/admin/login">
⚙️ Administration
</a>

<h1>🌍 Opportunités internationales</h1>

<p>
💼 Emplois • 🎓 Bourses • 💰 Stages rémunérés
</p>

<p>
Trouvez des opportunités internationales
et locales selon les offres disponibles.
</p>

</header>

<section class="search">

<form method="get">

<input
name="keyword"
value="{{ keyword }}"
placeholder="Exemple : informatique, ingénieur..."
>

<select name="country">

{% for code, name in countries.items() %}

<option
value="{{ code }}"
{% if code == country %}selected{% endif %}
>
{{ name }}
</option>

{% endfor %}

</select>

<select name="categorie">

<option value="emploi"
{% if categorie == "emploi" %}selected{% endif %}
>
💼 Emplois
</option>

<option value="bourse"
{% if categorie == "bourse" %}selected{% endif %}
>
🎓 Bourses
</option>

<option value="stage_remunere"
{% if categorie == "stage_remunere" %}selected{% endif %}
>
💰 Stages rémunérés
</option>

<option value="tous"
{% if categorie == "tous" %}selected{% endif %}
>
Toutes les catégories
</option>

</select>

<button name="search" value="1">
🔎 Rechercher
</button>

</form>

</section>

{% if offres %}

{% for offre in offres %}

<article class="card">

<h2>{{ offre["titre"] }}</h2>

<p>
🏢 <b>{{ offre["entreprise"] }}</b>
</p>

<p>
🌍 {{ offre["pays"] }}
{% if offre["localisation"] %}
— {{ offre["localisation"] }}
{% endif %}
</p>

<p>
📂 {{ offre["categorie"] }}
</p>

{% if offre["salaire_min"] or offre["salaire_max"] %}

<p>
💰 Salaire :
{{ offre["salaire_min"] or "" }}
-
{{ offre["salaire_max"] or "" }}
</p>

{% endif %}

<p>{{ offre["description"] }}</p>

{% if offre["lien"] %}

<p>
<a
href="{{ offre["lien"] }}"
target="_blank"
rel="noopener noreferrer"
>
👉 Voir l'offre / Candidater
</a>
</p>

{% endif %}

</article>

{% endfor %}

{% else %}

<div class="card">

<h2>
🔎 Aucune offre enregistrée pour cette recherche.
</h2>

<p>
Effectuez une recherche pour récupérer
les offres disponibles.
</p>

</div>

{% endif %}

</div>

</body>
</html>
"""


HTML_LOGIN = """
<!doctype html>
<html lang="fr">

<head>
<meta charset="utf-8">
<meta name="viewport"
content="width=device-width,initial-scale=1">
<title>Administration</title>

<style>
body {
    font-family: Arial;
    background: #f4f6f8;
    padding: 30px;
}

.box {
    max-width: 450px;
    margin: auto;
    background: white;
    padding: 25px;
    border-radius: 15px;
}

input,
button {
    width: 100%;
    box-sizing: border-box;
    padding: 12px;
    margin: 8px 0;
}
</style>

</head>

<body>

<div class="box">

<h1>⚙️ Administration</h1>

<form method="post">

<input
type="password"
name="key"
placeholder="Clé administrateur"
required
>

<button>
🔐 Se connecter
</button>

</form>

{% if message %}
<p>{{ message }}</p>
{% endif %}

</div>

</body>
</html>
"""


HTML_ADMIN = """
<!doctype html>
<html lang="fr">

<head>

<meta charset="utf-8">
<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>Administration</title>

<style>

body {
    font-family: Arial;
    background: #f4f6f8;
    padding: 20px;
}

.container {
    max-width: 1200px;
    margin: auto;
}

.card {
    background: white;
    padding: 20px;
    margin: 15px 0;
    border-radius: 15px;
}

button,
a {
    padding: 10px;
    margin: 5px;
}

.delete {
    color: #b00020;
}

</style>

</head>

<body>

<div class="container">

<p>
<a href="/">🌍 Voir le site</a>
|
<a href="/admin/logout">Déconnexion</a>
</p>

<h1>⚙️ Administration</h1>

<p>
{{ offres|length }} offres affichées.
</p>

{% for offre in offres %}

<div class="card">

<h2>{{ offre["titre"] }}</h2>

<p>🏢 {{ offre["entreprise"] }}</p>
<p>🌍 {{ offre["pays"] }}</p>
<p>📂 {{ offre["categorie"] }}</p>

{% if offre["lien"] %}

<p>
🔗
<a
href="{{ offre["lien"] }}"
target="_blank"
>
Lien de candidature
</a>
</p>

{% endif %}

<a href="/admin/modifier/{{ offre["id"] }}">
✏️ Modifier
</a>

<form
method="post"
action="/admin/supprimer/{{ offre["id"] }}"
style="display:inline"
>

<button
class="delete"
type="submit"
>
🗑️ Supprimer
</button>

</form>

</div>

{% endfor %}

</div>

</body>
</html>
"""


HTML_EDIT = """
<!doctype html>
<html lang="fr">

<head>

<meta charset="utf-8">
<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>Modifier une offre</title>

<style>

body {
    font-family: Arial;
    background: #f4f6f8;
    padding: 20px;
}

.box {
    max-width: 800px;
    margin: auto;
    background: white;
    padding: 25px;
    border-radius: 15px;
}

input,
textarea,
select,
button {
    width: 100%;
    box-sizing: border-box;
    padding: 12px;
    margin: 8px 0;
}

textarea {
    min-height: 200px;
}

</style>

</head>

<body>

<div class="box">

<h1>✏️ Modifier l'offre</h1>

<form method="post">

<label>Titre</label>

<input
name="titre"
value="{{ offre["titre"] }}"
required
>

<label>Entreprise</label>

<input
name="entreprise"
value="{{ offre["entreprise"] or "" }}"
>

<label>Pays</label>

<input
name="pays"
value="{{ offre["pays"] or "" }}"
>

<label>Localisation</label>

<input
name="localisation"
value="{{ offre["localisation"] or "" }}"
>

<label>Catégorie</label>

<select name="categorie">

<option value="Emploi"
{% if offre["categorie"] == "Emploi" %}
selected
{% endif %}
>
💼 Emploi
</option>

<option value="Bourse"
{% if offre["categorie"] == "Bourse" %}
selected
{% endif %}
>
🎓 Bourse
</option>

<option value="Stage rémunéré"
{% if offre["categorie"] == "Stage rémunéré" %}
selected
{% endif %}
>
💰 Stage rémunéré
</option>

</select>

<label>Description</label>

<textarea
name="description"
>{{ offre["description"] or "" }}</textarea>

<label>Lien de candidature</label>

<input
name="lien"
value="{{ offre["lien"] or "" }}"
>

<button>
💾 Enregistrer
</button>

</form>

<a href="/admin">
⬅️ Retour
</a>

</div>

</body>
</html>
"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port
)
