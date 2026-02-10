import uuid
import datetime
from datetime import timedelta
from roombooker.storage import StorageManager

class JobManager:
    def __init__(self):
        self.storage = StorageManager()
        self.jobs = self.storage.get_jobs()

    def save(self):
        self.storage.save_json(self.storage.jobs_path, self.jobs)

    def add_job(self, type, start, end, category, days=None, target_date=None):
        job = {
            "id": str(uuid.uuid4())[:8],
            "type": type,  # "recurring" or "onetime"
            "time_start": start,
            "time_end": end,
            "category": category,
            "status": "active",
            "last_booked": None, # Speichert das Datum der letzten erfolgreichen Buchung
            "created_at": datetime.datetime.now().strftime("%d.%m.%Y")
        }
        
        if type == "recurring":
            job["days"] = days  # ["Mon", "Tue", ...]
        elif type == "onetime":
            job["target_date"] = target_date
            
        self.jobs.append(job)
        self.save()
        print(f"[JOBS] Neuer Job gespeichert (ID: {job['id']})")
        return job

    def delete_job(self, job_id):
        self.jobs = [j for j in self.jobs if j["id"] != job_id]
        self.save()
        print(f"[JOBS] Job {job_id} gelöscht.")

    def get_active_jobs(self):
        return [j for j in self.jobs if j.get("status") == "active"]

    def get_due_jobs(self):
        """
        Filtert Jobs, die HEUTE ausgeführt werden müssen.
        Regel: Wir buchen exakt 14 Tage im Voraus (Midnight Sniper)
        oder füllen Lücken für Onetime-Events.
        Returns: Liste von Tupeln (job, date_string_to_book)
        """
        due_items = []
        today = datetime.date.today()
        # Das Uni-Fenster öffnet sich meist 14 Tage im Voraus
        target_horizon_date = today + timedelta(days=14)
        
        # Hilfs-Mapping für Wochentage
        # 0=Mon, 1=Tue, ...
        weekday_map = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        
        for job in self.get_active_jobs():
            # --- TYP 1: SERIEN (Recurring) ---
            if job["type"] == "recurring":
                # Wir prüfen primär das Datum in 14 Tagen (Sniper-Logik)
                horizon_weekday = weekday_map[target_horizon_date.weekday()]
                
                if horizon_weekday in job["days"]:
                    date_str = target_horizon_date.strftime("%d.%m.%Y")
                    
                    # Check: Haben wir genau diesen Tag schon gebucht?
                    if job.get("last_booked") == date_str:
                        continue # Schon erledigt
                        
                    due_items.append((job, date_str))

            # --- TYP 2: EINMALIG (Onetime) ---
            elif job["type"] == "onetime":
                t_date = datetime.datetime.strptime(job["target_date"], "%d.%m.%Y").date()
                date_str = job["target_date"]

                # Check 1: Ist das Datum schon vorbei?
                if t_date < today:
                    print(f"[JOBS] Onetime Job {job['id']} ist abgelaufen (Datum war {date_str}). Deaktiviere...")
                    job["status"] = "expired"
                    self.save()
                    continue

                # Check 2: Ist es schon gebucht?
                if job.get("last_booked") == date_str:
                    continue 

                # Check 3: Ist es innerhalb des 14-Tage Fensters?
                # Wir erlauben hier auch Gap-Filling (z.B. morgen), nicht nur exakt 14 Tage
                days_until = (t_date - today).days
                if 0 <= days_until <= 14:
                    due_items.append((job, date_str))
                else:
                    # Zu weit in der Zukunft -> Lokal ignorieren
                    pass 

        return due_items

    def mark_executed(self, job_id, date_str):
        for job in self.jobs:
            if job["id"] == job_id:
                job["last_booked"] = date_str
        self.save()