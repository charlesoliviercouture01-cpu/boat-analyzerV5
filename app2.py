from flask import Flask, request, render_template_string, send_file, url_for
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)

# ================= CONFIG =================
CFG = {
    "tps_min": 90,
    "tps_max": 105,
    "lambda_min": 0.75,
    "lambda_max": 1.05,
    "fuel_min": 40,
    "fuel_max": 60,
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

<style>
.header-row{
height:120px;
}

.logo-box{
height:120px;
display:flex;
align-items:center;
justify-content:center;
}

.logo-box img{
max-height:95px;
object-fit:contain;
}

.title-box{
height:120px;
display:flex;
align-items:center;
justify-content:center;
}
</style>
</head>

<body class="p-4 bg-dark text-light">
<div class="container">

<div class="row header-row mb-5">
<div class="col-3 logo-box">
<img src="{{ url_for('static', filename='p_logo_zoom.png') }}">
</div>

<div class="col-6 title-box">
<h1 class="m-0 text-center">Boat Data Analyzer</h1>
</div>

<div class="col-3 logo-box">
<img src="{{ url_for('static', filename='image_copy.png') }}">
</div>
</div>

<form method="post" action="/upload" enctype="multipart/form-data">

<div class="row mb-4">

<div class="col-md-4">
<input class="form-control" name="location" placeholder="Emplacement" required>
</div>

<div class="col-md-4">
<input class="form-control"
type="number"
step="0.1"
name="ambient_temp"
placeholder="Température ambiante (°C)"
required>
</div>

</div>

<input class="form-control mb-3" type="file" name="file" required>
<button class="btn btn-primary">Analyser</button>

</form>

{% if table %}
<hr class="my-5">

<h2 class="text-center mb-4 {{ 'text-danger' if cheat else 'text-success' }}">
{{ etat_global }}
</h2>

<div class="d-flex justify-content-center mb-4">
<a class="btn btn-success btn-lg" href="{{ download }}">Télécharger CSV</a>
</div>

<div class="table-responsive mb-5">
{{ table|safe }}
</div>
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
        sep=",",
        engine="python",
        on_bad_lines="skip"
    )

    if len(raw) < 25:
        return pd.DataFrame()

    header = raw.iloc[19]
    df = raw.iloc[22:].copy()

    df.columns = header

    # supprime colonne vide "19" si présente
    if "19" in df.columns:
        df = df.drop(columns=["19"])

    return df.reset_index(drop=True)

# ================= ANALYSE =================
def analyze_dataframe(df, ambient_temp):

    if df.empty:
        return df, False, None

    df = df.copy()

    # Sécurisation colonnes
    required = [
        "Section Time",
        "TPS (Main)",
        "Lambda 1",
        "Fuel Pressure",
        "ECT"
    ]

    for col in required:
        if col not in df.columns:
            return df, False, None

    df["Time"] = pd.to_numeric(df["Section Time"], errors="coerce")
    df["TPS"] = pd.to_numeric(df["TPS (Main)"], errors="coerce")
    df["AFR"] = pd.to_numeric(df["Lambda 1"], errors="coerce")
    df["Fuel"] = pd.to_numeric(df["Fuel Pressure"], errors="coerce")
    df["ECT"] = pd.to_numeric(df["ECT"], errors="coerce")

    df = df.dropna(subset=["Time","TPS","AFR","Fuel","ECT"])

    if len(df) < 5:
        return df, False, None

    df["Lambda"] = df["AFR"] / 14.7

    # Ajustement température (robuste)
    df["ECT_corr"] = df["ECT"] - ambient_temp

    df["OUT_TPS"] = ~df["TPS"].between(CFG["tps_min"], CFG["tps_max"])
    df["OUT_LAMBDA"] = ~df["Lambda"].between(CFG["lambda_min"], CFG["lambda_max"])
    df["OUT_FUEL"] = ~df["Fuel"].between(CFG["fuel_min"], CFG["fuel_max"])

    # Cheat seulement si plusieurs erreurs simultanées
    df["OUT"] = (
        df["OUT_TPS"] &
        df["OUT_LAMBDA"] &
        df["OUT_FUEL"]
    )

    df["dt"] = df["Time"].diff().fillna(0)

    cumul = 0
    cheat = False
    cheat_time = None

    for t,out,dt in zip(df["Time"], df["OUT"], df["dt"]):

        if bool(out):
            cumul += dt
            if cumul >= CFG["cheat_delay"]:
                cheat = True
                cheat_time = t
                break
        else:
            cumul = 0

    return df, cheat, cheat_time

# ================= ROUTES =================
@app.route("/")
def index():
    return render_template_string(
        HTML,
        table=None,
        download=None,
        etat_global="",
        cheat=False
    )

@app.route("/health")
def health():
    return "OK"

@app.route("/upload", methods=["POST"])
def upload():

    try:

        file = request.files["file"]
        location = request.form["location"]
        ambient_temp = float(request.form["ambient_temp"].replace(",", "."))

        df = load_link_csv(file)
        df, cheat, cheat_time = analyze_dataframe(df, ambient_temp)

        if cheat:
            etat = f"FAIL – Début {round(cheat_time,2)} s"
        else:
            etat = f"PASS | {location}"

        fname = f"result_{datetime.now().timestamp()}.csv"
        path = os.path.join(UPLOAD_DIR, fname)
        df.to_csv(path, index=False)

        table = df.head(150).to_html(
            classes="table table-dark table-striped",
            index=False
        )

        return render_template_string(
            HTML,
            table=table,
            download=url_for("download", fname=fname),
            etat_global=etat,
            cheat=cheat
        )

    except Exception as e:

        return f"""
        <h2 style='color:red'>Erreur analyse</h2>
        <pre>{e}</pre>
        """

@app.route("/download")
def download():
    return send_file(
        os.path.join(UPLOAD_DIR, request.args["fname"]),
        as_attachment=True
    )

# ================= RENDER =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
