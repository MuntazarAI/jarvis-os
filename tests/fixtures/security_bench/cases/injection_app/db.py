import pickle
import subprocess

import yaml


def run(cmd, blob, stream, cursor, user_id):
    result = eval(cmd)
    subprocess.run(cmd, shell=True)
    pickle.loads(blob)
    yaml.load(stream)
    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
    return result
