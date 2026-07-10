import os
import psycopg2


def make_placeholders(n):
    """IN 句用のプレースホルダ文字列 `%s, %s, ...`（n 個）を生成する。"""
    return ', '.join(['%s'] * n)


def execute_in_query(conn, sql_template, in_values, params=None):
    """
    IN 句のプレースホルダを件数に応じて生成してクエリを実行し、全行（fetchall の結果）を返す。

    - sql_template 内の `{placeholders}` を、in_values の件数分の `%s, %s, ...` に置換する。
      テンプレートに複数の `{placeholders}` がある場合は、すべて同じ件数で置換される。
    - params が None の場合は in_values をそのままパラメータとして渡す。
      複数の IN 句で同じ値を使い回す場合は params を明示する（例: values * 3）。

    SQL インジェクションはプレースホルダ（パラメータ化クエリ）で防いでおり安全。
    """
    query = sql_template.replace("{placeholders}", make_placeholders(len(in_values)))
    exec_params = tuple(in_values) if params is None else tuple(params)
    with conn.cursor() as cursor:
        cursor.execute(query, exec_params)
        return cursor.fetchall()


class DatabaseManager:
    """
    複数データベースへの接続を一元管理し、必要なタイミングでコネクションを張るクラス。
    """
    def __init__(self):
        self._conns = {
            "tax": None,
            "bp": None,
            "bs": None,
            "dra": None,
            "submitter": None,
            "gea": None
        }

    def _get_conn(self, key, db_env_name, is_tax=False):
        if self._conns.get(key) is None:
            if is_tax:
                db_name = os.environ.get("PGDATABASE") or os.environ.get("DDBJ_DB_NAME")
                db_port = os.environ.get("PGPORT") or os.environ.get("DDBJ_DB_PORT")
                self._conns[key] = psycopg2.connect(
                    host=os.environ.get("DB_HOST"),
                    port=db_port,
                    dbname=db_name,
                    user=os.environ.get("DDBJ_DB_USER"),
                    password=os.environ.get("DDBJ_DB_PASS")
                )
            else:
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

    def get_submitter_conn(self):
        return self._get_conn("submitter", "SUBMITTER_DB_NAME")

    def get_gea_conn(self):
        return self._get_conn("gea", "GEA_DB_NAME")

    def close_all(self):
        for conn in self._conns.values():
            if conn:
                conn.close()