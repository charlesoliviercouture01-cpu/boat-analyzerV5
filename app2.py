from flask import Flask, request, render_template_string, send_file, url_for
import pandas as pd
import os
from datetime import datetime
import matplotlib.pyplot as plt

app = Flask(__name__)

# ================= HRL CONFIG =================
CFG = {
    "tps_min": 90,
    "tps_max": 105,

    "lambda_min": 0.78,
    "lambda_max": 1.02,

    "fuel_target": 55,
    "fuel_tol": 3,

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
<title>Boat Data Analyzer HRL</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>

<body class="p-4 bg-dark text-light">
<div class="container">

<h1 class="text-center mb-4">Boat Data Analyzer HRL</h1>

<form method="post" action="/upload" enctype="multipart/form-data">

<div class="row mb-3">
<div class="col-md-4">
<input class="form-control" name="location" placeholder="Emplacement" required>
</div>

<div class="col-md-4">
<input class="form-control"
type="number"
step="0.1"
name="ambient_temp"
placeholder="Température ambiante" required>
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

<div class="text-center">
<img src="{{ graph }}">
</div>

<div class="table-responsive mt-4">
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
        engine="python",
        on_bad_lines="skip"
    )

    if len(raw) < 25:
        return pd.DataFrame()

    header = raw.iloc[19]
    df = raw.iloc[22:].copy()

    df.columns = header

    df = df.loc[:, ~df.columns.astype(str).str.contains("^Unnamed")]

    return df.reset_index(drop=True)

# ================= ANALYSE HRL =================
def analyze_dataframe(df, ambient):

    if df.empty:
        return df, False, None

    df = df.copy()

    df["Time"] = pd.to_numeric(df.get("Section Time"), errors="coerce")
    df["TPS"] = pd.to_numeric(df.get("TPS (Main)"), errors="coerce")
    df["AFR"] = pd.to_numeric(df.get("Lambda 1"), errors="coerce")
    df["Fuel"] = pd.to_numeric(df.get("Fuel Pressure"), errors="coerce")
    df["ECT"] = pd.to_numeric(df.get("ECT"), errors="coerce")

    df = df.dropna(subset=["Time","TPS","AFR","Fuel"])

    if len(df) < 10:
        return df, False, None

    df["Lambda"] = df["AFR"] / 14.7

    fuel_min = CFG["fuel_target"] - CFG["fuel_tol"]
    fuel_max = CFG["fuel_target"] + CFG["fuel_tol"]

    df["OUT_TPS"] = ~df["TPS"].between(CFG["tps_min"], CFG["tps_max"])
    df["OUT_LAMBDA"] = ~df["Lambda"].between(CFG["lambda_min"], CFG["lambda_max"])
    df["OUT_FUEL"] = ~df["Fuel"].between(fuel_min, fuel_max)

    # cheat dynamique (2 paramètres)
    df["OUT_COUNT"] = (
        df["OUT_TPS"].astype(int) +
        df["OUT_LAMBDA"].astype(int) +
        df["OUT_FUEL"].astype(int)
    )

    df["OUT"] = df["OUT_COUNT"] >= 2

    df["dt"] = df["Time"].diff().fillna(0)

    cumul = 0
    cheat = False
    cheat_time = None

    for t,out,dt in zip(df["Time"], df["OUT"], df["dt"]):

        if out:
            cumul += dt
            if cumul >= CFG["cheat_delay"]:
                cheat = True
                cheat_time = t
                break
        else:
            cumul = 0

    return df, cheat, cheat_time

# ================= GRAPH =================
def create_graph(df):

    path = "/tmp/graph.png"

    plt.figure(figsize=(10,4))

    plt.plot(df["Time"], df["TPS"], label="TPS")
    plt.plot(df["Time"], df["Lambda"], label="Lambda")

    plt.legend()
    plt.grid()

    plt.savefig(path)
    plt.close()

    return path

# ================= ROUTES =================
@app.route("/")
def index():
    return render_template_string(HTML, table=None)

@app.route("/upload", methods=["POST"])
def upload():

    try:

        file = request.files["file"]
        ambient = float(request.form["ambient_temp"])
        location = request.form["location"]

        df = load_link_csv(file)
        df, cheat, cheat_time = analyze_dataframe(df, ambient)

        if cheat:
            etat = f"FAIL – {round(cheat_time,2)} s"
        else:
            etat = f"PASS – {location}"

        graph_path = create_graph(df)

        table = df.head(150).to_html(
            classes="table table-dark table-striped",
            index=False
        )

        return render_template_string(
            HTML,
            table=table,
            cheat=cheat,
            etat=etat,
            graph=url_for("static_graph")
        )

    except Exception as e:
        return f"<pre>{e}</pre>"

@app.route("/static_graph")
def static_graph():
    return send_file("/tmp/graph.png")

# ================= RENDER =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
