import os
import sys
import logging
from flask import Flask, render_template, request, redirect, url_for
from roombooker.storage import StorageManager
from roombooker.jobs import JobManager
from main import run_booking_logic, run_sync
from roombooker.config import BASE_DIR, SETTINGS_FILE

app = Flask(__name__)
app.secret_key = "secret"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/jobs')
def jobs():
    jm = JobManager()
    return render_template('jobs.html', jobs=jm.jobs)

@app.route('/jobs/add', methods=['POST'])
def add_job():
    jm = JobManager()
    jm.create_job(
        name=request.form.get('name'),
        date_str=request.form.get('date'),
        start=request.form.get('start'),
        end=request.form.get('end'),
        category=request.form.get('category'),
        accounts=4,
        repetition=request.form.get('frequency')
    )
    return redirect(url_for('jobs'))

@app.route('/sync')
def sync():
    run_sync()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
