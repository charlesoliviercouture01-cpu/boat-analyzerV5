from flask import Flask, request, render_template_string, send_file, url_for
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)

# ================= CONFIG HRL =================
CFG = {
    "tps_min": 90,
    "tps_max": 105,
    "lambda_min": 0.75,
    "lambda_max": 1.05,
    "fuel_max": 55,
    "cheat_delay": 0.4
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

<div class="row mb-4">
  <div class="col-md-4">
    <input class="form-control" name="location" placeholder="Location" required>
  </div>

  <div class="col-md-4">
    <input class="form-control" type="number" step="0.1"
           name="ambient_temp"
           placeholder="Température ambiante"
           required>
  </div>
</div>

<input class="form-control mb-3" type="file" name="file" required>
<button class="btn btn-primary">Analyser</button>

</form>

{% if table %}
<hr>

<h2 class="text-center {{ 'text-danger' if cheat else 'text-success' }}">
{{ etat }}
</h2>

<div class="text-center mb-3">
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

# ================= CSV ROBUSTE =================
def load_link_csv(file):

    raw = pd.read_csv(
        file,
        header=None,
        sep=",",
        engine="python",
        on_bad_lines="skip"
    )

    # sécurité si fichier plus court
    if len(raw) < 25:
        raise ValueError("CSV trop court")

    header = raw.iloc[19]
    df = raw.iloc[22:].copy()
    df.columns = header
    df = df.reset_index(drop=True)

    return df


# ================= ANALYSE =================
def analyze_dataframe(df, ambient_temp):

    df = df.copy()

    df["Time"] = pd.to_numeric(df.get("Section Time"), errors="coerce")
    df["TPS"] = pd.to_numeric(df.get("TPS (Main)"), errors="coerce")
    df["AFR"] = pd.to_numeric(df.get("Lambda 1"), errors="coerce")
    df["Fuel"] = pd.to_numeric(df.get("Fuel Pressure"), errors="coerce")
    df["ECT"] = pd.to_numeric(df.get("ECT"), errors="coerce")

    df = df.dropna(subset=["Time","TPS","AFR","Fuel","ECT"])

    df["Lambda"] = df["AFR"] / 14.7

    df["OUT_TPS"] = ~df["TPS"].between(CFG["tps_min"], CFG["tps_max"])
    df["OUT_LAMBDA"] = ~df["Lambda"].between(CFG["lambda_min"], CFG["lambda_max"])

    # règle HRL
    df["OUT_FUEL"] = df["Fuel"] > CFG["fuel_max"]

    df["OUT"] = (
        df["OUT_TPS"] |
        df["OUT_LAMBDA"] |
        df["OUT_FUEL"]
    )

    df["dt"] = df["Time"].diff().fillna(0)

    cumul = 0
    cheat = False
    cheat_time = None

    for t, out, dt in zip(df["Time"], df["OUT"], df["dt"]):
        if out:
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
        cheat=False,
        etat=""
    )


@app.route("/upload", methods=["POST"])
def upload():

    try:
        file = request.files["file"]

        ambient_temp = float(
            request.form["ambient_temp"].replace(",", ".")
        )

        location = request.form["location"]

        df = load_link_csv(file)

        df, cheat, cheat_time = analyze_dataframe(
            df,
            ambient_temp
        )

        if cheat:
            etat = f"CHEAT détecté à {cheat_time:.2f}s"
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
            cheat=cheat,
            etat=etat,
            download=url_for("download", fname=fname)
        )

    except Exception as e:
        return f"Erreur analyse : {str(e)}"


@app.route("/download")
def download():
    return send_file(
        os.path.join(UPLOAD_DIR, request.args["fname"]),
        as_attachment=True
    )


# ================= RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
