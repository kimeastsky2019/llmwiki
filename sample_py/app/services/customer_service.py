"""고객 도메인 서비스."""
from datetime import datetime

from sqlalchemy.orm import Session

from ..models.entities import Customer, CustomerHistory


class CustomerService:
    """고객 등록/수정/조회를 담당한다."""

    def list_customers(self, db: Session, keyword: str = ""):
        query = db.query(Customer)
        if keyword:
            query = query.filter(Customer.name.like(f"%{keyword}%"))
        return query.all()

    def register(self, db: Session, name: str, grade_cd: str):
        customer = Customer(name=name, grade_cd=grade_cd)
        db.add(customer)
        history = CustomerHistory(customer_id=customer.id, changed_at=datetime.utcnow())
        db.add(history)
        db.commit()
        return customer

    def touch_login(self, db: Session, customer: Customer):
        customer.last_login = datetime.utcnow()
        db.commit()

    def remove(self, db: Session, customer_id: int):
        db.query(Customer).filter(Customer.id == customer_id).delete()
        db.commit()
