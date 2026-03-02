from flask import Flask, request, render_template_string, send_file, url_for
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)

# ================= CONFIG HRL =================
CFG = {

    # Pleine charge moteur
    "tps_min": 90,
    "tps_max": 105,

    # Lambda course sécuritaire
    "lambda_min": 0.78,
    "lambda_max": 0.95,

    # Fuel pression réelle terrain HRL
    "fuel_min": 52,
    "fuel_max": 56,

    # délai anti faux positif
    "cheat_delay": 0.7
}

UPLOAD_DIR = "/tmp"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ================= HTML =================
HTML = """
<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Boat Data Analyzer</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>

<body class="p-4 bg-dark text-light">
<div class="container">

<h2 class="text-center mb-4">Boat Data Analyzer</h2>

<form method="post" action="/upload" enctype="multipart/form-data">

<div class="row mb-3">
  <div class="col-md-4">
    <input class="form-control" name="location" placeholder="Emplacement" required>
  </div>

  <div class="col-md-4">
    <input class="form-control" name="ambient_temp" placeholder="Température ambiante (°C)" required>
  </div>
</div>

<input class="form-control mb-3" type="file" name="file" required>
<button class="btn btn-primary">Analyser</button>

</form>

{% if table %}

<hr class="my-4">

<h3 class="text-center {{ 'text-danger' if cheat else 'text-success' }}">
{{ etat_global }}
</h3>

<div class="d-flex justify-content-center mb-4">
<a class="btn btn-success" href="{{ download }}">Télécharger CSV</a>
</div>

<div class="table-responsive">
{{ table|safe }}
</div>

{% endif %}

</div>
</body>
</html>
"""

# ================= LECTURE CSV RAPIDE =================
def load_link_csv(file):

    raw = pd.read_csv(
        file,
        header=None,
        sep=",",
        engine="python",
        on_bad_lines="skip"
    )

    header = raw.iloc[19]
    df = raw.iloc[22:].copy()

    df.columns = header
    df = df.reset_index(drop=True)

    return df


# ================= ANALYSE ULTRA RAPIDE =================
def analyze_dataframe(df):

    df = df.copy()

    df["Time"] = pd.to_numeric(df.get("Section Time"), errors="coerce")
    df["TPS"] = pd.to_numeric(df.get("TPS (Main)"), errors="coerce")
    df["AFR"] = pd.to_numeric(df.get("Lambda 1"), errors="coerce")
    df["Fuel"] = pd.to_numeric(df.get("Fuel Pressure"), errors="coerce")

    df = df.dropna(subset=["Time","TPS","AFR","Fuel"])

    df["Lambda"] = df["AFR"] / 14.7

    # Conditions individuelles
    df["OUT_FUEL"] = ~df["Fuel"].between(CFG["fuel_min"], CFG["fuel_max"])
    df["OUT_TPS"] = ~df["TPS"].between(CFG["tps_min"], CFG["tps_max"])
    df["OUT_LAMBDA"] = ~df["Lambda"].between(CFG["lambda_min"], CFG["lambda_max"])

    # IMPORTANT : seulement si les 3 sont hors norme
    df["OUT"] = (
        df["OUT_FUEL"] &
        df["OUT_TPS"] &
        df["OUT_LAMBDA"]
    )

    # délai
    df["dt"] = df["Time"].diff().fillna(0)

    df["cum_out"] = (df["OUT"] * df["dt"]).cumsum()

    cheat_detected = df["cum_out"].max() >= CFG["cheat_delay"]

    return df, cheat_detected


# ================= ROUTES =================
@app.route("/")
def index():
    return render_template_string(
        HTML,
        table=None,
        cheat=False,
        etat_global="",
        download=None
    )


@app.route("/upload", methods=["POST"])
def upload():

    file = request.files["file"]

    df = load_link_csv(file)

    df, cheat = analyze_dataframe(df)

    if cheat:
        etat = "Datalog NOT compliant with rules"
    else:
        etat = "PASS – Datalog conforme HRL"

    fname = f"result_{datetime.now().timestamp()}.csv"
    path = os.path.join(UPLOAD_DIR, fname)

    df.to_csv(path, index=False)

    table = df.head(120).to_html(
        classes="table table-dark table-striped",
        index=False
    )

    return render_template_string(
        HTML,
        table=table,
        cheat=cheat,
        etat_global=etat,
        download=url_for("download", fname=fname)
    )


@app.route("/download")
def download():
    return send_file(
        os.path.join(UPLOAD_DIR, request.args["fname"]),
        as_attachment=True
    )


# ================= RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
