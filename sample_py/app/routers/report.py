"""계좌 리포트 (Flask 블루프린트)."""
from flask import Blueprint

from ..models.entities import Account

bp = Blueprint("report", __name__, url_prefix="/report")


@bp.route("/accounts", methods=["GET"])
def account_report():
    """계좌 잔액 리포트."""
    from ..db import session

    return [dict(id=a.id, balance=a.balance) for a in session.query(Account).all()]


@bp.route("/raw", methods=["GET"])
def raw_report():
    """원시 SQL 집계."""
    from ..db import engine

    return engine.execute(
        "SELECT c.name, SUM(a.balance) FROM tb_customer c JOIN tb_account a ON a.customer_id = c.id GROUP BY c.name"
    )
