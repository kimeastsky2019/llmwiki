"""고객 정보 관리 API."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..services.customer_service import CustomerService

router = APIRouter(prefix="/api/v1/customers", tags=["고객"])
service = CustomerService()


@router.get("/")
def list_customers(keyword: str = "", db: Session = Depends(lambda: None)):
    """고객 목록 조회."""
    return service.list_customers(db, keyword)


@router.post("/")
def create_customer(name: str, grade_cd: str, db: Session = Depends(lambda: None)):
    """고객 등록."""
    return service.register(db, name, grade_cd)


@router.delete("/{customer_id}")
def delete_customer(customer_id: int, db: Session = Depends(lambda: None)):
    """고객 삭제."""
    service.remove(db, customer_id)
    return {"ok": True}
