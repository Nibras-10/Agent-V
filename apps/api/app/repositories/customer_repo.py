from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.entities import Customer


class CustomerRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, customer_id: str) -> Optional[Customer]:
        stmt = select(Customer).where(Customer.id == customer_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_external_ref(self, ref: str) -> Optional[Customer]:
        stmt = select(Customer).where(Customer.external_ref == ref)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def update_contact(self, customer_id: str, display_name: Optional[str] = None, phone: Optional[str] = None) -> Optional[Customer]:
        customer = await self.get_by_id(customer_id)
        if not customer:
            return None
        if display_name is not None:
            customer.display_name = display_name
        if phone is not None:
            customer.phone = phone
        await self.db.commit()
        await self.db.refresh(customer)
        return customer
