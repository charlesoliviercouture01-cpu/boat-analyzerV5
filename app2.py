from flask import Flask, request, render_template_string, send_file, url_for
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)

# ================= CONFIG HRL =================
CFG = {
    "fuel_limit": 55,
    "fuel_noise_tolerance": 54.8,
    "temp_offset": 20,
    "cheat_delay": 0.30
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

<h1 class="text-center mb-4">Boat Data Analyzer</h1>

<form method="post" action="/upload" enctype="multipart/form-data">

<div class="row mb-3">
  <div class="col-md-6">
    <input class="form-control" name="location" placeholder="Embarcation / Emplacement" required>
  </div>

  <div class="col-md-6">
    <input class="form-control" type="number" step="0.1"
           name="ambient_temp"
           placeholder="Température ambiante (°C)" required>
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

    header = raw.iloc[19]
    df = raw.iloc[22:].copy()
    df.columns = header

    df = df.loc[:, df.columns.notna()]

    return df.reset_index(drop=True)

# ================= ANALYSE =================
def analyze_dataframe(df, ambient_temp):

    df = df.copy()

    df["Time"] = pd.to_numeric(df.get("Section Time"), errors="coerce")
    df["Fuel"] = pd.to_numeric(df.get("Fuel Pressure"), errors="coerce")
    df["ECT"] = pd.to_numeric(df.get("ECT"), errors="coerce")

    df = df.dropna(subset=["Time", "Fuel", "ECT"])
    df = df[df["Time"].diff().fillna(0) >= 0]

    # ---------- règles ----------
    df["OUT_FUEL"] = df["Fuel"] < CFG["fuel_noise_tolerance"]
    df["OUT_TEMP"] = df["ECT"] > (ambient_temp + CFG["temp_offset"])

    df["OUT"] = df["OUT_FUEL"] | df["OUT_TEMP"]

    df["dt"] = df["Time"].diff().fillna(0)

    cumul = 0
    cheat = False
    cheat_time = None

    for t, out, dt in zip(df["Time"], df["OUT"], df["dt"]):

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

@app.route("/upload", methods=["POST"])
def upload():

    try:

        file = request.files["file"]
        location = request.form["location"]
        ambient_temp = float(request.form["ambient_temp"].replace(",", "."))

        df = load_link_csv(file)
        df, cheat, cheat_time = analyze_dataframe(df, ambient_temp)

        if cheat:
            etat = "Datalog NOT compliant with rules"
        else:
            etat = f"PASS | {location}"

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
            download=url_for("download", fname=fname),
            etat_global=etat,
            cheat=cheat
        )

    except Exception as e:
        return f"Erreur analyse : {e}"

@app.route("/download")
def download():
    return send_file(
        os.path.join(UPLOAD_DIR, request.args["fname"]),
        as_attachment=True
    )

# ================= RENDER =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
