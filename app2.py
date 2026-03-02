from flask import Flask, request, render_template_string, send_file, url_for
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)

# ================= CONFIG HRL =================
CFG = {
    "tps_full_load": 85,

    # règles HRL réelles terrain
    "fuel_min": 50,
    "fuel_max": 60,

    "lambda_min": 0.72,
    "lambda_max": 1.05,

    "cheat_delay": 0.5
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
    <input class="form-control" name="ambient_temp" placeholder="Température ambiante °C" required>
  </div>
</div>

<input class="form-control mb-3" type="file" name="file" required>
<button class="btn btn-primary">Analyser</button>

</form>

{% if table %}
<hr>

<h3 class="text-center {{ 'text-danger' if cheat else 'text-success' }}">
{{ etat }}
</h3>

<div class="table-responsive">
{{ table|safe }}
</div>

<a class="btn btn-success mt-3" href="{{ download }}">Télécharger CSV</a>

{% endif %}

</div>
</body>
</html>
"""

# ================= CSV ROBUSTE =================
def load_link_csv(file):

    raw = pd.read_csv(
        file,
        header=None,
        engine="python",
        sep=",",
        on_bad_lines="skip"
    )

    header = raw.iloc[19]
    df = raw.iloc[22:].copy()

    df.columns = header
    df = df.reset_index(drop=True)

    return df


# ================= ANALYSE HRL =================
def analyze_dataframe(df):

    df = df.copy()

    df["Time"] = pd.to_numeric(df.get("Section Time"), errors="coerce")
    df["TPS"] = pd.to_numeric(df.get("TPS (Main)"), errors="coerce")
    df["AFR"] = pd.to_numeric(df.get("Lambda 1"), errors="coerce")
    df["Fuel"] = pd.to_numeric(df.get("Fuel Pressure"), errors="coerce")

    df = df.dropna(subset=["Time","TPS","AFR","Fuel"])

    df["Lambda"] = df["AFR"] / 14.7

    # Analyse seulement pleine charge
    df = df[df["TPS"] > CFG["tps_full_load"]]

    if len(df) == 0:
        return df, False

    df["dt"] = df["Time"].diff().fillna(0)

    # FAIL seulement fuel illégal
    df["CHEAT"] = df["Fuel"] < CFG["fuel_min"]

    df["cum"] = (df["CHEAT"] * df["dt"]).cumsum()

    cheat_detected = df["cum"].max() >= CFG["cheat_delay"]

    return df, cheat_detected


# ================= ROUTES =================
@app.route("/")
def index():
    return render_template_string(
        HTML,
        table=None,
        cheat=False,
        etat="",
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
        etat=etat,
        download=url_for("download", fname=fname)
    )


@app.route("/download")
def download():
    return send_file(
        os.path.join(UPLOAD_DIR, request.args["fname"]),
        as_attachment=True
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
