import os
import psycopg2

class DatabaseManager:
    """
    複数データベースへの接続を一元管理し、必要なタイミングでコネクションを張るクラス。
    """
    def __init__(self):
        self._conns = {
            "tax": None,
            "bp": None,
            "bs": None,
            "dra": None
        }

    def _get_conn(self, key, db_env_name, is_tax=False):
        if self._conns[key] is None:
            if is_tax:
                self._conns[key] = psycopg2.connect(
                    host=os.environ.get("PGHOST"),
                    port=os.environ.get("PGPORT"),
                    dbname=os.environ.get("PGDATABASE"),
                    user=os.environ.get("USER"),
                    password=os.environ.get("USER")
                )
            else:
                # メタデータDBは共通の接続先 (.env の設定値をそのまま使用)
                self._conns[key] = psycopg2.connect(
                    host=os.environ.get("DB_HOST"),
                    port=os.environ.get("DB_PORT"),
                    dbname=os.environ.get(db_env_name),
                    user=os.environ.get("DB_USER"),
                    password=os.environ.get("DB_PASS")
                )
        return self._conns[key]

    def get_tax_conn(self):
        return self._get_conn("tax", "", is_tax=True)

    def get_bp_conn(self):
        return self._get_conn("bp", "BP_DB_NAME")

    def get_bs_conn(self):
        return self._get_conn("bs", "BS_DB_NAME")

    def get_dra_conn(self):
        return self._get_conn("dra", "DRA_DB_NAME")

    def close_all(self):
        for conn in self._conns.values():
            if conn:
                conn.close()