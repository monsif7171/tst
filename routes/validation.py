"""Pydantic models for request validation."""
from pydantic import BaseModel, Field, field_validator, ValidationError, ConfigDict
from typing import Optional, List, Any, Dict
from config import MIN_PASSWORD_LENGTH


class BaseAppModel(BaseModel):
    model_config = ConfigDict(extra="allow")


def validate_payload(model_cls, data):
    """Validate data against a Pydantic model and return (validated_dict, error_message)."""
    if not isinstance(data, dict):
        return None, "صيغة البيانات غير صحيحة (يجب أن تكون كائن JSON)"
    try:
        instance = model_cls.model_validate(data)
        return instance.model_dump(), None
    except ValidationError as err:
        errors = err.errors()
        if errors:
            first = errors[0]
            field = " -> ".join(str(loc) for loc in first.get("loc", []))
            msg = first.get("msg", "قيمة غير صالحة")
            return None, f"خطأ في الحقل ({field}): {msg}"
        return None, "خطأ في التحقق من البيانات المدخلة"


class LoginRequest(BaseAppModel):
    """Login request validation."""
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1)

    @field_validator('username')
    @classmethod
    def validate_username(cls, v):
        v = v.strip()
        if not v:
            raise ValueError('Username cannot be empty or whitespace only')
        return v


class UserCreateRequest(BaseAppModel):
    """User creation request validation."""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH)
    full_name: Optional[str] = None
    role: str = Field(default='sales')
    branch_id: Optional[int] = None

    @field_validator('username')
    @classmethod
    def validate_username(cls, v):
        v = v.strip()
        if not v:
            raise ValueError('Username cannot be empty')
        return v

    @field_validator('role')
    @classmethod
    def validate_role(cls, v):
        allowed = {'admin', 'pharmacist', 'sales'}
        if v not in allowed:
            raise ValueError(f'Role must be one of: {allowed}')
        return v


class ProductRequest(BaseAppModel):
    """Product creation/update request validation."""
    name: str = Field(..., min_length=1, max_length=200)
    generic_name: Optional[str] = None
    strength: Optional[str] = None
    form: Optional[str] = None
    manufacturer: Optional[str] = None
    category: Optional[str] = None
    category_id: Optional[int] = None
    barcode: Optional[str] = None
    purchase_price: float = Field(default=0, ge=0)
    sale_price: float = Field(default=0, ge=0)
    purchase_price_usd: float = Field(default=0, ge=0)
    sale_price_usd: float = Field(default=0, ge=0)
    min_qty: float = Field(default=0, ge=0)
    unit: str = Field(default='piece')
    strip_qty: float = Field(default=1, gt=0)
    carton_qty: float = Field(default=1, gt=0)
    supplier_id: Optional[int] = None
    is_prescription: bool = Field(default=False)

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        v = v.strip()
        if not v:
            raise ValueError('Product name is required')
        return v


class SaleItemRequest(BaseAppModel):
    """Sale item validation."""
    product_id: int = Field(..., gt=0)
    qty: float = Field(..., gt=0)
    price: Optional[float] = Field(default=None, ge=0)
    instructions: Optional[str] = None


class SaleRequest(BaseAppModel):
    """Sale creation request validation."""
    items: List[SaleItemRequest] = Field(..., min_length=1)
    discount: float = Field(default=0, ge=0)
    paid: Optional[float] = Field(default=None, ge=0)
    customer_id: Optional[int] = None
    payment_method: str = Field(default='cash')
    note: Optional[str] = None
    branch_id: Optional[int] = None
    points_redeemed: float = Field(default=0, ge=0)

    @field_validator('payment_method')
    @classmethod
    def validate_payment_method(cls, v):
        allowed = {'cash', 'card', 'mobile', 'bank'}
        if v not in allowed:
            raise ValueError(f'Payment method must be one of: {allowed}')
        return v


class PurchaseItemRequest(BaseAppModel):
    """Purchase item validation."""
    product_id: int = Field(..., gt=0)
    qty: float = Field(..., gt=0)
    cost: float = Field(..., ge=0)
    batch_no: Optional[str] = None
    expiry_date: Optional[str] = None


class PurchaseRequest(BaseAppModel):
    """Purchase creation request validation."""
    items: List[PurchaseItemRequest] = Field(..., min_length=1)
    supplier_id: Optional[int] = None
    invoice_no: Optional[str] = None
    discount: float = Field(default=0, ge=0)
    extra_cost: float = Field(default=0, ge=0)
    paid: float = Field(default=0, ge=0)
    note: Optional[str] = None
    branch_id: Optional[int] = None


class SupplierRequest(BaseAppModel):
    """Supplier creation request validation."""
    name: str = Field(..., min_length=1, max_length=200)
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    balance: float = Field(default=0, ge=0)

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        v = v.strip()
        if not v:
            raise ValueError('Supplier name is required')
        return v


class CustomerRequest(BaseAppModel):
    """Customer creation request validation."""
    name: Optional[str] = None
    phone: str = Field(..., min_length=1)
    loyalty_no: Optional[str] = None

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError('Phone is required')
        return v


class ExpenseRequest(BaseAppModel):
    """Expense creation request validation."""
    amount: float = Field(..., gt=0)
    category: Optional[str] = None
    note: Optional[str] = None
    payment_type: Optional[str] = Field(default='day')
    branch_id: Optional[int] = None


class ShiftOpenRequest(BaseAppModel):
    """Shift open request validation."""
    opening_cash: float = Field(default=0, ge=0)
    branch_id: Optional[int] = None


class ShiftCloseRequest(BaseAppModel):
    """Shift close request validation."""
    closing_cash: float = Field(..., ge=0)
    note: Optional[str] = None


class PaymentRequest(BaseAppModel):
    """Supplier payment request validation."""
    amount: float = Field(..., gt=0)
    note: Optional[str] = None
    branch_id: Optional[int] = None


class ReturnRequest(BaseAppModel):
    """Return request validation."""
    sale_id: int = Field(..., gt=0)
    product_id: int = Field(..., gt=0)
    qty: float = Field(..., gt=0)
    reason: Optional[str] = None


class BatchRequest(BaseAppModel):
    """Batch creation request validation."""
    product_id: int = Field(..., gt=0)
    batch_no: Optional[str] = None
    expiry_date: Optional[str] = None
    qty: float = Field(default=0, ge=0)
    cost: float = Field(default=0, ge=0)
    branch_id: Optional[int] = None
