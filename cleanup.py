import glob, os
def clean():
    for f in glob.glob("*.png") + glob.glob("*.log"):
        try: os.remove(f); print(f"Deleted {f}")
        except: pass
if __name__ == "__main__": clean()
