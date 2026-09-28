from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator


def nonnegative_money(value: str) -> str:
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("Money must be a decimal string.") from error
    if not amount.is_finite() or amount < 0:
        raise ValueError("Money must be finite and nonnegative.")
    return value


Money = Annotated[str, AfterValidator(nonnegative_money)]
Status = Literal["Received", "Dispatched", "Delivered", "Sold", "Cancelled"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Order(Contract):
    id: str
    runId: str
    orderKey: str
    eventId: str
    sequence: int = Field(ge=1, le=4)
    number: str
    status: Status
    eventTime: AwareDatetime
    orderedAt: AwareDatetime
    dispatchedAt: AwareDatetime | None
    deliveredAt: AwareDatetime | None
    expectedAt: AwareDatetime
    brand: str
    brandScope: str
    portfolioStatus: str
    chain: str
    destinationId: str
    destination: str
    city: str
    region: str
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    isDispatched: bool
    isLate: bool
    netNZD: Money
    salesNZD: Money


class Line(Contract):
    id: str
    orderId: str
    eventId: str
    number: int = Field(ge=1)
    productCode: str
    product: str
    category: str
    brand: str
    portfolioStatus: str
    quantity: int = Field(gt=0)
    unit: str
    pack: str
    storage: str
    batchId: str
    status: Status
    netNZD: Money
    productionLine: Literal["cheese", "cultured", "butter", "dairy"]


class Activity(Contract):
    id: str
    orderId: str
    orderNumber: str
    eventType: Literal["ORDER_RECEIVED", "ORDER_DISPATCHED", "ORDER_DELIVERED", "SALE_COMPLETED", "ORDER_CANCELLED"]
    eventTime: AwareDatetime
    brand: str
    chain: str
    city: str


class Totals(Contract):
    totalOrders: int = Field(ge=0)
    awaitingDispatch: int = Field(ge=0)
    inTransit: int = Field(ge=0)
    delivered: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    lateOrders: int = Field(ge=0)
    salesNZD: Money
    lastEventAt: AwareDatetime | None


class Snapshot(Contract):
    generatedAt: AwareDatetime
    windowHours: Literal[24]
    maxOrders: Literal[200]
    scope: Literal["NZ supermarket deliveries"]
    productionSource: str
    orders: list[Order] = Field(max_length=200)
    lines: list[Line] = Field(max_length=600)
    activity: list[Activity] = Field(max_length=40)
    totals: Totals

    @model_validator(mode="after")
    def consistent_snapshot(self):
        orders = {order.id: order for order in self.orders}
        if len(orders) != len(self.orders) or len({line.id for line in self.lines}) != len(self.lines):
            raise ValueError("Duplicate order or line identities.")
        if self.totals.totalOrders < len(self.orders):
            raise ValueError("Window totals cannot be smaller than the displayed order list.")
        covered_orders = set()
        for line in self.lines:
            order = orders.get(line.orderId)
            if order is None or order.eventId != line.eventId or order.status != line.status:
                raise ValueError("Line data must belong to the order's current lifecycle event.")
            covered_orders.add(line.orderId)
        if covered_orders != set(orders):
            raise ValueError("Some order line items are missing; retry after ingestion catches up.")
        return self
