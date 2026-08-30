"""데이터 모델 정의."""
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Customer(Base):
    """고객 마스터."""
    __tablename__ = "tb_customer"

    id = Column(Integer, primary_key=True)
    name = Column(String(60), nullable=False)
    grade_cd = Column(String(2))
    last_login = Column(DateTime)


class CustomerHistory(Base):
    """고객 변경 이력."""
    __tablename__ = "tb_customer_hist"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer)
    changed_at = Column(DateTime)


class Account(Base):
    """계좌."""
    __tablename__ = "tb_account"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer)
    balance = Column(Integer)
