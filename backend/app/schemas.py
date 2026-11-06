from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

class ChatRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question", mode="before")
    @classmethod
    def trim_question(cls, value):
        if not isinstance(value, str):
            raise ValueError("问题必须是字符串")
        return value.strip()

class OrderQuery(BaseModel):
    order_id: str
    @field_validator("order_id")
    @classmethod
    def validate_order(cls, value):
        import re
        if not re.fullmatch(r"SQ\d{6}", value):
            raise ValueError("订单号格式应为 SQ 加 6 位数字")
        return value

class TicketDraftRequest(OrderQuery):
    ticket_type: str = Field(default="refund", pattern="^(refund|return|exchange|logistics|other)$")
    reason: str = Field(min_length=2, max_length=1000)
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")

class ApprovalModifications(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ticket_type: Literal["refund", "return", "exchange", "logistics", "other"] = Field(default=None)
    reason: str = Field(default=None, min_length=2, max_length=1000)
    priority: Literal["low", "normal", "high", "urgent"] = Field(default=None)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value):
        if not isinstance(value, str):
            raise ValueError("工单原因必须是字符串")
        return value.strip()

class ApprovalDecision(BaseModel):
    reason: Optional[str] = None
    modifications: Optional[ApprovalModifications] = None

class ReindexRequest(BaseModel):
    version: Optional[int] = None

class FeedbackRequest(BaseModel):
    message_id: str
    helpful: bool
    reason: Optional[str] = None

class ReportRequest(BaseModel):
    order_id: str
    ticket_id: Optional[str] = None

class ApiResponse(BaseModel):
    ok: bool = True
    data: Any
