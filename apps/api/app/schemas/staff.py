from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class StaffTicketUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Optional[Literal["open", "in_progress", "pending_approval", "handed_off", "resolved"]] = None
    priority: Optional[Literal["low", "normal", "high", "urgent"]] = None
