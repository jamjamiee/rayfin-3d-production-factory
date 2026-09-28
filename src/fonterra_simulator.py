# %% Imports and catalogue
"""Synthetic, ownership-aware Fonterra order-to-sale demonstration.

This source is embedded in the standalone Fabric notebook by build_notebook.py.
No real orders, prices, customers, inventory, or brand-specific SKUs are used.
"""

import copy
import heapq
import json
import math
import os
import random
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import quote, urlparse


CATALOG_AS_OF = "2026-09-12"
EVENT_SCHEMA_VERSION = "1.1"
SOURCES = {
    "fonterra": "https://www.fonterra.com/nz/en/our-co-operative/our-brands.html",
    "sale": "https://www.fonterra.com/nz/en/our-stories/media/fonterra-completes-sale-of-mainland-group-to-lactalis.html",
    "consumer": "https://www.mainlanddairy.com/en/brands.html",
    "afp": "https://www.anchorfoodprofessionals.com/global/en.html",
    "nzmp": "https://www.nzmp.com/global/en.html",
    "nutiani": "https://www.nutiani.com/nz/en.html",
    "bega": "https://www.fonterra.com/nz/en/our-stories/media/update-on-divestment-of-consumer-and-associated-businesses.html",
    "australia": "https://www.fonterra.com/au/en/about-us/our-brands.html",
    "jumpstart": "https://jumpstart.fabric.microsoft.com/catalog/retail-sales/",
}


@dataclass(frozen=True)
class Brand:
    code: str
    name: str
    portfolio_status: str
    channel: str
    market: str
    categories: tuple[str, ...]
    source_keys: tuple[str, ...]
    note: str
    event_eligible: bool = True


BRANDS = (
    Brand("AFP", "Anchor Food Professionals", "CurrentFonterra", "Foodservice", "SG",
          ("Butter", "Cream", "Cheese", "Cream cheese"), ("fonterra", "afp", "sale"),
          "Retained foodservice scope represented by Singapore; AFP is not Fonterra-operated in every region."),
    Brand("NZMP", "NZMP", "CurrentFonterra", "Ingredients", "SG",
          ("Milk powder", "Milk concentrate", "Dairy fats", "Cream", "Cheese",
           "Milk protein", "Whey protein", "Casein and caseinates", "Lactose",
           "Specialty nutrition ingredients"), ("fonterra", "nzmp", "sale"),
          "Illustrative ingredient orders; product trademarks such as SureProtein are not separate corporate brands here."),
    Brand("NUT", "Nutiani", "CurrentFonterra", "NutritionB2B", "SG",
          ("Probiotic ingredients",), ("fonterra", "nutiani"),
          "B2B nutrition ingredients, not a supermarket range; no dosage or health claims."),
    Brand("ANC-CN", "Anchor", "CurrentFonterra", "Retail", "CN",
          ("Dairy assortment",), ("sale",),
          "Greater China consumer ownership retained. Assortment is a placeholder, not a verified China SKU range."),
    Brand("FARM", "Farm Source", "CurrentFonterra", "FarmerServices", "NZ",
          ("Farmer services",), ("fonterra",),
          "Included for corporate brand coverage; excluded from dairy sales because this is a farmer-services brand.",
          event_eligible=False),
    Brand("ANC-LEG", "Anchor", "DivestedComparison", "Retail", "NZ",
          ("Dairy assortment",), ("consumer", "sale"),
          "Former consumer portfolio outside Greater China; must not be grouped with retained China ownership."),
    Brand("ANL", "Anlene", "DivestedComparison", "Retail", "MY",
          ("Adult nutrition",), ("consumer", "sale"),
          "Divested consumer nutrition brand; hypothetical pack, not a validated formulation."),
    Brand("ANM", "Anmum", "DivestedComparison", "Retail", "MY",
          ("Maternal and family nutrition",), ("consumer", "sale"),
          "Divested consumer nutrition brand; no infant-feeding or health recommendations."),
    Brand("MAIN", "Mainland", "DivestedComparison", "Retail", "NZ",
          ("Cheese", "Butter"), ("consumer", "sale"), "Divested consumer cheese and butter."),
    Brand("PI", "Perfect Italiano", "DivestedComparison", "Retail", "AU",
          ("Cooking cheese",), ("consumer", "sale"), "Divested cooking-cheese brand."),
    Brand("KAP", "Kapiti", "DivestedComparison", "Retail", "NZ",
          ("Artisan cheese", "Greek-style yoghurt"), ("consumer", "sale"),
          "ASCII display name for Kapiti. Ice cream is not asserted by the reviewed current directory."),
    Brand("WS", "Western Star", "DivestedComparison", "Retail", "AU",
          ("Butter", "Spreads", "Cream"), ("consumer", "sale"), "Divested Australian consumer brand."),
    Brand("BEGA", "Bega", "LicensedDivestedComparison", "Retail", "AU",
          ("Cheese",), ("consumer", "bega", "sale"),
          "Australian business licences were included in the sale; this does not assert Fonterra owned the trademark."),
    Brand("CHES", "Chesdale", "DivestedComparison", "Retail", "NZ",
          ("Cheese",), ("consumer", "sale"),
          "NZ routing is hypothetical; reviewed directory does not establish an exhaustive territorial schedule."),
    Brand("FERN", "Fernleaf", "DivestedComparison", "Retail", "MY",
          ("Dairy assortment",), ("consumer", "sale"), "Divested Malaysian dairy brand."),
    Brand("FF", "Fresh 'n Fruity", "DivestedComparison", "Retail", "NZ",
          ("Fruit yoghurt",), ("consumer", "sale"), "Divested consumer yoghurt brand."),
    Brand("RAT", "Ratthi", "DivestedComparison", "Retail", "LK",
          ("Dairy assortment",), ("consumer", "sale"),
          "Divested Sri Lankan dairy brand; specific current product forms have not been verified."),
)

# FX is fixed demonstration data: NZD per one unit of local currency, not live FX.
MARKETS = {
    "NZ": ("New Zealand", "Auckland", -36.8485, 174.7633, "NZD", "1.00"),
    "AU": ("Australia", "Melbourne", -37.8136, 144.9631, "AUD", "1.10"),
    "SG": ("Singapore", "Singapore", 1.3521, 103.8198, "SGD", "1.25"),
    "MY": ("Malaysia", "Kuala Lumpur", 3.1390, 101.6869, "MYR", "0.38"),
    "CN": ("China", "Shanghai", 31.2304, 121.4737, "CNY", "0.23"),
    "LK": ("Sri Lanka", "Colombo", 6.9271, 79.8612, "LKR", "0.0055"),
}

NZ_SUPERMARKET_CHAINS = ("New World", "PAK'nSAVE", "Woolworths", "Four Square", "FreshChoice", "SuperValue")
NZ_DESTINATION_CITIES = (
    ("Auckland", "Auckland", -36.8485, 174.7633),
    ("Wellington", "Wellington", -41.2866, 174.7756),
    ("Christchurch", "Canterbury", -43.5321, 172.6362),
    ("Hamilton", "Waikato", -37.7870, 175.2793),
    ("Tauranga", "Bay of Plenty", -37.6878, 176.1651),
    ("Dunedin", "Otago", -45.8788, 170.5028),
)

# category -> (illustrative pack, selling unit, NZD reference price in cents, storage)
PRODUCT_TEMPLATES = {
    "Butter": ("500 g", "pack", 750, "Chilled"),
    "Cream": ("1 L", "carton", 1150, "Chilled"),
    "Cheese": ("1 kg", "pack", 1850, "Chilled"),
    "Cream cheese": ("1 kg", "tub", 1700, "Chilled"),
    "Milk powder": ("25 kg", "bag", 14500, "Ambient"),
    "Milk concentrate": ("20 kg", "pail", 12000, "Chilled"),
    "Dairy fats": ("20 kg", "pail", 18000, "Ambient"),
    "Milk protein": ("20 kg", "bag", 30000, "Ambient"),
    "Whey protein": ("20 kg", "bag", 28000, "Ambient"),
    "Casein and caseinates": ("20 kg", "bag", 32000, "Ambient"),
    "Lactose": ("25 kg", "bag", 8500, "Ambient"),
    "Specialty nutrition ingredients": ("5 kg", "bag", 45000, "Ambient"),
    "Probiotic ingredients": ("1 kg", "pack", 60000, "Chilled"),
    "Dairy assortment": ("1 demo unit", "demo unit", 900, "Chilled"),
    "Adult nutrition": ("900 g", "tin", 2700, "Ambient"),
    "Maternal and family nutrition": ("800 g", "tin", 3000, "Ambient"),
    "Cooking cheese": ("500 g", "pack", 1100, "Chilled"),
    "Artisan cheese": ("200 g", "pack", 1200, "Chilled"),
    "Greek-style yoghurt": ("450 g", "tub", 750, "Chilled"),
    "Spreads": ("500 g", "tub", 650, "Chilled"),
    "Fruit yoghurt": ("600 g", "tub", 650, "Chilled"),
}


def cents(value):
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def amount(value_in_cents):
    return float(Decimal(value_in_cents) / 100)


def catalog_rows():
    return [
        {
            "ScopeId": brand.code, "Brand": brand.name, "Status": brand.portfolio_status,
            "Channel": brand.channel, "DemoMarket": brand.market,
            "Categories": ", ".join(brand.categories), "GeneratesEvents": brand.event_eligible,
            "Note": brand.note, "Sources": [SOURCES[key] for key in brand.source_keys],
        }
        for brand in BRANDS
    ]


def build_products(include_divested_brands=False, include_nz_supermarket_orders=False):
    for name, value in (("include_divested_brands", include_divested_brands),
                        ("include_nz_supermarket_orders", include_nz_supermarket_orders)):
        if type(value) is not bool:
            raise ValueError(f"{name} must be a boolean.")
    products = []
    for brand_index, brand in enumerate(BRANDS, 1):
        if not brand.event_eligible:
            continue
        nz_comparison = include_nz_supermarket_orders and brand.market == "NZ" and brand.channel == "Retail"
        if brand.portfolio_status != "CurrentFonterra" and not include_divested_brands and not nz_comparison:
            continue
        fx = Decimal(MARKETS[brand.market][5])
        for category_index, category in enumerate(brand.categories, 1):
            pack, unit, base_cents, storage = PRODUCT_TEMPLATES[category]
            products.append({
                "ProductKey": brand_index * 100 + category_index,
                "ProductCode": f"SIM-{brand.code}-{category_index:02d}",
                "ProductName": f"{brand.name} - {category} - DEMO",
                "Brand": brand.name, "BrandScopeId": brand.code,
                "PortfolioStatus": brand.portfolio_status, "CategoryName": category,
                "Channel": brand.channel, "MarketCode": brand.market,
                "PackSize": pack, "QuantityUnit": unit, "StorageCondition": storage,
                "ReferencePriceCents": int((Decimal(base_cents) / fx).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP)),
                "BrandSourceUrls": [SOURCES[key] for key in brand.source_keys],
            })
    return products


# %% Order generation
@dataclass(frozen=True)
class SimulationConfig:
    max_orders: int = 60
    max_duration_seconds: float = 120.0
    orders_per_second: float = 1.0
    max_pending_orders: int = 100
    seed: int = 42
    include_divested_brands: bool = False
    include_nz_supermarket_orders: bool = False
    cancellation_probability: float = 0.05
    late_delivery_probability: float = 0.15
    dispatch_delay_seconds: float = 5.0
    delivery_delay_seconds: float = 10.0
    sale_delay_seconds: float = 2.0

    def validate(self):
        for key in ("max_orders", "max_pending_orders"):
            value = getattr(self, key)
            if type(value) is not int or value < 1:
                raise ValueError(f"{key} must be a positive integer.")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer.")
        if type(self.include_divested_brands) is not bool:
            raise ValueError("include_divested_brands must be a boolean.")
        if type(self.include_nz_supermarket_orders) is not bool:
            raise ValueError("include_nz_supermarket_orders must be a boolean.")
        for key in ("max_duration_seconds", "orders_per_second", "dispatch_delay_seconds",
                    "delivery_delay_seconds", "sale_delay_seconds"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} must be finite and greater than zero.")
        for key in ("cancellation_probability", "late_delivery_probability"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{key} must be between zero and one.")


def order_destination(product, order_number):
    """Create an invented delivery location; chain names do not imply supply contracts."""
    market = product["MarketCode"]
    _, city, latitude, longitude, _, _ = MARKETS[market]
    supermarket = market == "NZ" and product["Channel"] == "Retail"
    region, chain = "", ""
    if supermarket:
        chain_index = (order_number - 1) % len(NZ_SUPERMARKET_CHAINS)
        city_index = ((order_number - 1) // len(NZ_SUPERMARKET_CHAINS)) % len(NZ_DESTINATION_CITIES)
        chain = NZ_SUPERMARKET_CHAINS[chain_index]
        city, region, latitude, longitude = NZ_DESTINATION_CITIES[city_index]
        destination_id = f"SIM-NZ-SUP-{city_index + 1:02d}-{chain_index + 1:02d}"
        destination_name = f"SIM - {chain} - {city} demo outlet"
        destination_type = "Supermarket"
    else:
        destination_id = f"SIM-{market}-{product['Channel']}-01"
        destination_name = f"SIM - {city} - {product['Channel']} customer"
        destination_type = {
            "Retail": "RetailOutlet", "Foodservice": "FoodserviceCustomer",
            "Ingredients": "Manufacturer", "NutritionB2B": "Manufacturer",
        }[product["Channel"]]
    destination = {
        "DestinationId": destination_id, "DestinationName": destination_name,
        "DestinationType": destination_type, "DestinationCountryCode": market,
        "DestinationCity": city, "DestinationRegion": region,
        "DestinationLatitude": latitude, "DestinationLongitude": longitude,
        "SupermarketChain": chain, "IsNZSupermarketDelivery": supermarket,
        "IsDispatchedToNZSupermarket": False,
    }
    if supermarket:
        destination["StoreKey"] = 10000 + city_index * 100 + chain_index
    return destination


def generate_sale(rng, products, order_number, run_id, order_time):
    """Build an order snapshot, rather than unrelated random POS line items.

The first product rotates through the entire enabled catalogue; other lines
stay in that brand/market/channel. The lifecycle assigns revenue only at sale.
"""
    if not products:
        raise ValueError("At least one enabled product is required.")
    first = products[(order_number - 1) % len(products)]
    candidates = [p for p in products if p["BrandScopeId"] == first["BrandScopeId"]
                  and p["ProductKey"] != first["ProductKey"]]
    selected = [first] + rng.sample(candidates, rng.randint(0, min(2, len(candidates))))
    market_code = first["MarketCode"]
    country, city, latitude, longitude, currency, fx = MARKETS[market_code]
    destination = order_destination(first, order_number)
    city, latitude, longitude = (destination["DestinationCity"], destination["DestinationLatitude"],
                                 destination["DestinationLongitude"])
    order_key = str(uuid.uuid5(run_id, f"order:{order_number}"))
    lines = []
    for line_number, product in enumerate(selected, 1):
        unit_cents = max(1, round(product["ReferencePriceCents"] * rng.uniform(0.9, 1.1)))
        discount_percent = rng.choice((0, 0, 5, 10))
        net_cents = int((Decimal(unit_cents) * (100 - discount_percent) / 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
        if destination["IsNZSupermarketDelivery"]:
            quantity = rng.randint(12, 120)
        else:
            quantity = rng.randint(1, 6) if first["Channel"] == "Retail" else rng.randint(5, 40)
        line_cents = net_cents * quantity
        reporting_cents = int((Decimal(line_cents) * Decimal(fx)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
        line = {key: value for key, value in product.items() if key != "ReferencePriceCents"}
        line.update({
            "LineNumber": line_number, "Quantity": quantity,
            "UnitPrice": amount(unit_cents), "NetPrice": amount(net_cents),
            "UnitCost": amount(int(net_cents * rng.uniform(0.6, 0.8))),
            "DiscountPercent": discount_percent, "LineNetAmount": amount(line_cents),
            "LineNetAmountNZD": amount(reporting_cents),
            "CurrencyCode": currency, "ExchangeRate": float(fx),
            "BatchId": f"SIM-LOT-{order_time:%Y%m%d}-{product['ProductKey']}",
        })
        lines.append(line)
    return {
        "SchemaVersion": EVENT_SCHEMA_VERSION, "IsSynthetic": True, "CatalogAsOf": CATALOG_AS_OF,
        "SimulationRunId": str(run_id), "OrderKey": order_key,
        "OrderNumber": f"SIM-{order_number:07d}",
        "OrderDate": int(order_time.timestamp()), "DispatchDate": None, "DeliveryDate": None,
        "CustomerKey": rng.randint(100000, 199999), "StoreKey": rng.randint(1, 12),
        "CustomerName": f"SIM-{market_code}-{first['Channel']}-Customer",
        "StoreName": destination["DestinationName"], "WarehouseId": f"SIM-{market_code}-DC01",
        "Channel": first["Channel"], "Brand": first["Brand"],
        "BrandScopeId": first["BrandScopeId"], "PortfolioStatus": first["PortfolioStatus"],
        "Country": country, "MarketCode": market_code, "City": city,
        "Latitude": latitude, "Longitude": longitude,
        "CurrencyCode": currency, "ReportingCurrencyCode": "NZD", "ExchangeRate": float(fx),
        "OrderNetAmount": amount(sum(cents(line["LineNetAmount"]) for line in lines)),
        "OrderNetAmountNZD": amount(sum(cents(line["LineNetAmountNZD"]) for line in lines)),
        "TaxIncluded": False, **destination, "lines": lines,
    }


def validate_event(event):
    if event["EventType"] not in {
        "ORDER_RECEIVED", "ORDER_DISPATCHED", "ORDER_DELIVERED", "SALE_COMPLETED", "ORDER_CANCELLED"
    }:
        raise ValueError("Unknown EventType.")
    if not event["IsSynthetic"] or not event["lines"]:
        raise ValueError("Synthetic events require at least one line.")
    nz_delivery = event["DestinationType"] == "Supermarket" and event["DestinationCountryCode"] == "NZ"
    if event["IsNZSupermarketDelivery"] != nz_delivery:
        raise ValueError("The NZ supermarket flag must match the delivery destination.")
    if event["IsDispatchedToNZSupermarket"] != (nz_delivery and event["DispatchDate"] is not None):
        raise ValueError("A supermarket order is dispatched only after an actual dispatch timestamp exists.")
    if nz_delivery and (event["Channel"] != "Retail" or event["CurrencyCode"] != "NZD"
                        or not event["SupermarketChain"]):
        raise ValueError("NZ supermarket deliveries require a retail destination, chain and NZD currency.")
    for line in event["lines"]:
        if line["Quantity"] <= 0 or line["CurrencyCode"] != event["CurrencyCode"]:
            raise ValueError("Invalid quantity or mixed currencies in an order.")
        if line["BrandScopeId"] != event["BrandScopeId"]:
            raise ValueError("An order cannot mix brand ownership scopes.")
        if cents(line["LineNetAmount"]) != cents(line["NetPrice"]) * line["Quantity"]:
            raise ValueError("Line amount does not reconcile.")
        expected = line["LineNetAmount"] if event["EventType"] == "SALE_COMPLETED" else 0
        if cents(line["SalesAmount"]) != cents(expected):
            raise ValueError("Revenue must be recognized only at SALE_COMPLETED.")
    if cents(event["OrderNetAmount"]) != sum(cents(line["LineNetAmount"]) for line in event["lines"]):
        raise ValueError("Order amount does not reconcile.")
    if cents(event["SalesAmount"]) != sum(cents(line["SalesAmount"]) for line in event["lines"]):
        raise ValueError("Sales amount does not reconcile.")


# %% Bounded lifecycle and streaming clock
class SalesSimulation:
    def __init__(self, config, *, start_time=None, run_id=None):
        config.validate()
        self.config = config
        self.products = build_products(config.include_divested_brands, config.include_nz_supermarket_orders)
        self.rng = random.Random(config.seed)
        self.run_id = uuid.UUID(str(run_id)) if run_id is not None else uuid.uuid4()
        self.start_time = start_time if start_time is not None else datetime.now(timezone.utc)
        if self.start_time.tzinfo is None or self.start_time.utcoffset() is None:
            raise ValueError("start_time must be timezone-aware.")
        self.start_time = self.start_time.astimezone(timezone.utc)
        self._orders = {}
        self._queue = []
        self._tie_breaker = 0
        self._started = False
        self.stats = {
            "run_id": str(self.run_id), "orders_created": 0, "events_generated": 0,
            "unfinished_orders": 0, "peak_pending_orders": 0, "stop_reason": "not_started",
            "event_counts": Counter(), "sales_cents_by_currency": Counter(),
        }

    def _schedule(self, elapsed):
        number = self.stats["orders_created"] + 1
        order_time = self.start_time + timedelta(seconds=elapsed)
        order = generate_sale(self.rng, self.products, number, self.run_id, order_time)
        cfg = self.config
        dispatch_due = elapsed + cfg.dispatch_delay_seconds
        delivery_due = dispatch_due + cfg.delivery_delay_seconds
        order["ExpectedDeliveryDate"] = int((self.start_time + timedelta(seconds=delivery_due)).timestamp())
        order["IsLate"] = False
        self._orders[order["OrderKey"]] = order
        stages = [(elapsed, "ORDER_RECEIVED")]
        if self.rng.random() < cfg.cancellation_probability:
            stages.append((elapsed + cfg.dispatch_delay_seconds / 2, "ORDER_CANCELLED"))
        else:
            if self.rng.random() < cfg.late_delivery_probability:
                delivery_due += cfg.delivery_delay_seconds
            stages.extend([
                (dispatch_due, "ORDER_DISPATCHED"),
                (delivery_due, "ORDER_DELIVERED"),
                (delivery_due + cfg.sale_delay_seconds, "SALE_COMPLETED"),
            ])
        for sequence, (due, event_type) in enumerate(stages, 1):
            self._tie_breaker += 1
            heapq.heappush(self._queue, (due, self._tie_breaker, order["OrderKey"], sequence, event_type))
        self.stats["orders_created"] = number
        self.stats["peak_pending_orders"] = max(self.stats["peak_pending_orders"], len(self._orders))

    def _emit(self, entry, elapsed, realtime):
        _, _, order_key, sequence, event_type = entry
        order = self._orders[order_key]
        timestamp = self.start_time + timedelta(seconds=elapsed)
        if event_type == "ORDER_DISPATCHED":
            order["DispatchDate"] = int(timestamp.timestamp())
        elif event_type == "ORDER_DELIVERED":
            order["DeliveryDate"] = int(timestamp.timestamp())
            order["IsLate"] = order["DeliveryDate"] > order["ExpectedDeliveryDate"]
        event = copy.deepcopy(order)
        event.update({
            "EventId": str(uuid.uuid5(self.run_id, f"{order_key}:{sequence}")),
            "EventSequence": sequence, "EventType": event_type,
            "EventTime": timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "ClockMode": "Realtime" if realtime else "VirtualPreview",
            "OrderStatus": {
                "ORDER_RECEIVED": "Received", "ORDER_DISPATCHED": "Dispatched",
                "ORDER_DELIVERED": "Delivered", "SALE_COMPLETED": "Sold",
                "ORDER_CANCELLED": "Cancelled",
            }[event_type],
            "DispatchId": f"SIM-DSP-{order_key}" if order["DispatchDate"] is not None else None,
            "CancellationReason": "Synthetic customer cancellation" if event_type == "ORDER_CANCELLED" else None,
            "SalesAmount": event["OrderNetAmount"] if event_type == "SALE_COMPLETED" else 0.0,
            "SalesAmountNZD": event["OrderNetAmountNZD"] if event_type == "SALE_COMPLETED" else 0.0,
            "OrderCountDelta": int(event_type == "ORDER_RECEIVED"),
            "IsDispatchedToNZSupermarket": order["IsNZSupermarketDelivery"] and order["DispatchDate"] is not None,
        })
        for line in event["lines"]:
            line["OrderedQuantityDelta"] = line["Quantity"] if event_type == "ORDER_RECEIVED" else 0
            line["DispatchedQuantityDelta"] = line["Quantity"] if event_type == "ORDER_DISPATCHED" else 0
            line["SoldQuantityDelta"] = line["Quantity"] if event_type == "SALE_COMPLETED" else 0
            line["SalesAmount"] = line["LineNetAmount"] if event_type == "SALE_COMPLETED" else 0.0
            line["SalesAmountNZD"] = line["LineNetAmountNZD"] if event_type == "SALE_COMPLETED" else 0.0
        validate_event(event)
        self.stats["events_generated"] += 1
        self.stats["event_counts"][event_type] += 1
        if event_type == "SALE_COMPLETED":
            self.stats["sales_cents_by_currency"][event["CurrencyCode"]] += cents(event["SalesAmount"])
        if event_type in ("SALE_COMPLETED", "ORDER_CANCELLED"):
            del self._orders[order_key]
        return event

    def events(self, *, realtime=False, clock=time.monotonic, sleeper=time.sleep):
        """Yield at most max_orders * 4 events, with a hard scheduling duration.

At a duration limit, unfinished orders are reported, not force-completed. A
network send already in progress can exceed that limit by its SDK timeout.
"""
        if type(realtime) is not bool:
            raise ValueError("realtime must be a boolean.")
        if self._started:
            raise RuntimeError("Create a new SalesSimulation for each run.")
        self._started = True
        cfg = self.config
        started = clock()
        elapsed = 0.0
        next_order = 0.0
        self.stats["stop_reason"] = "interrupted_or_consumer_stopped"
        try:
            while self._queue or self.stats["orders_created"] < cfg.max_orders:
                if realtime:
                    elapsed = clock() - started
                if elapsed >= cfg.max_duration_seconds:
                    self.stats["stop_reason"] = "duration_limit"
                    break
                if self._queue and self._queue[0][0] <= elapsed:
                    yield self._emit(heapq.heappop(self._queue), elapsed, realtime)
                    continue
                can_create = (self.stats["orders_created"] < cfg.max_orders
                              and len(self._orders) < cfg.max_pending_orders)
                if can_create and next_order <= elapsed:
                    self._schedule(elapsed)
                    next_order = elapsed + 1 / cfg.orders_per_second
                    continue
                candidates = [self._queue[0][0]] if self._queue else []
                if can_create:
                    candidates.append(next_order)
                next_due = min(*candidates, cfg.max_duration_seconds)
                if realtime:
                    sleeper(min(max(0.0, next_due - elapsed), 0.1))
                else:
                    elapsed = next_due
            else:
                self.stats["stop_reason"] = "completed"
        finally:
            self.stats["unfinished_orders"] = len(self._orders)


# %% Optional Eventstream publisher
def validate_eventstream_connection(connection):
    if not isinstance(connection, str) or not connection.strip():
        raise ValueError("The selected credential source did not supply an Eventstream connection string.")
    fields = {}
    for field in connection.strip().split(";"):
        if field:
            key, separator, value = field.partition("=")
            if not separator:
                raise ValueError("Invalid Eventstream connection string; use its Event Hubs-compatible source connection.")
            fields[key] = value
    endpoint = urlparse(fields.get("Endpoint", ""))
    if (endpoint.scheme != "sb" or not endpoint.hostname or not fields.get("EntityPath")
            or not fields.get("SharedAccessKeyName") or not fields.get("SharedAccessKey")):
        raise ValueError("Use a complete Event Hubs-compatible source connection string including EntityPath and SAS key.")
    return connection.strip()


def resolve_eventstream_connection(workspace_name, eventstream_name, source_name, *, client=None):
    """Resolve the custom endpoint with the notebook caller's Fabric identity.

Only names are configured. IDs and rotating credentials are obtained on every
run; connection responses must never be printed or saved in notebook outputs.
"""
    for name in (workspace_name, eventstream_name, source_name):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Workspace, Eventstream and custom source names are required.")
    if client is None:
        from sempy.fabric import FabricRestClient
        client = FabricRestClient()

    def read(path):
        response = client.get(path)
        if response.status_code != 200:
            raise RuntimeError(
                f"Fabric endpoint lookup failed (HTTP {response.status_code}). "
                "Check the configured names and the caller's Eventstream read/write permissions."
            )
        result = response.json()
        if not isinstance(result, dict):
            raise RuntimeError("Fabric endpoint lookup returned an invalid response.")
        return result

    def collection(path):
        next_path = path
        seen = set()
        while True:
            page = read(next_path)
            if not isinstance(page.get("value"), list):
                raise RuntimeError("Fabric item listing did not return a value array.")
            yield from page["value"]
            token = page.get("continuationToken")
            if not token:
                if page.get("continuationUri"):
                    raise RuntimeError("Fabric returned a continuation URI without a continuation token.")
                break
            if not isinstance(token, str) or token in seen:
                raise RuntimeError("Fabric returned an invalid or repeated continuation token.")
            seen.add(token)
            separator = "&" if "?" in path else "?"
            next_path = f"{path}{separator}continuationToken={quote(token, safe='')}"

    def unique_id(items, name, label):
        matches = [item for item in items if item.get("displayName") == name]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one {label} named '{name}'; found {len(matches)}.")
        return str(uuid.UUID(matches[0]["id"]))

    workspace_id = unique_id(collection("/v1/workspaces"), workspace_name, "workspace")
    items_path = f"/v1/workspaces/{workspace_id}/items?type=Eventstream"
    eventstream_id = unique_id(
        (item for item in collection(items_path) if item.get("type") == "Eventstream"),
        eventstream_name, "Eventstream",
    )
    base = f"/v1/workspaces/{workspace_id}/eventstreams/{eventstream_id}"
    topology = read(f"{base}/topology")
    if not isinstance(topology.get("sources"), list):
        raise RuntimeError("Fabric Eventstream topology did not return a sources array.")
    sources = [source for source in topology["sources"] if source.get("name") == source_name]
    if len(sources) != 1 or sources[0].get("type") != "CustomEndpoint":
        raise ValueError(f"Expected exactly one CustomEndpoint source named '{source_name}'.")
    source_id = str(uuid.UUID(sources[0]["id"]))
    connection = read(f"{base}/sources/{source_id}/connection")
    if connection.get("type") != "CustomEndpoint":
        raise ValueError("The selected source does not expose an Event Hubs-compatible custom endpoint.")
    keys = connection.get("accessKeys")
    if not isinstance(keys, dict):
        raise ValueError("The custom endpoint did not return access keys; check Eventstream read/write permissions.")
    return validate_eventstream_connection(keys.get("primaryConnectionString"))


def load_eventstream_connection(key_vault_url="", secret_name="", *, environment=None, secret_getter=None):
    """Load the Event Hubs-compatible custom endpoint secret; never print it."""
    env = os.environ if environment is None else environment
    if key_vault_url or secret_name:
        parsed = urlparse(key_vault_url)
        if (not secret_name or parsed.scheme != "https" or not parsed.hostname
                or not parsed.hostname.endswith(".vault.azure.net") or parsed.username
                or parsed.password or parsed.port is not None or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment):
            raise ValueError("Set a valid HTTPS Azure Key Vault URL and secret name.")
        if secret_getter is None:
            import notebookutils
            secret_getter = notebookutils.credentials.getSecret
        connection = secret_getter(key_vault_url, secret_name)
    else:
        connection = env.get("FONTERRA_EVENTSTREAM_CONNECTION_STRING", "")
    if not isinstance(connection, str) or not connection.strip():
        raise ValueError("Live mode requires a Key Vault secret or FONTERRA_EVENTSTREAM_CONNECTION_STRING.")
    return validate_eventstream_connection(connection)


def publish_event(producer, event, *, event_data_class=None):
    if event["ClockMode"] != "Realtime":
        raise ValueError("Virtual preview events must not be published. Run the realtime generator.")
    if event_data_class is None:
        from azure.eventhub import EventData
        event_data_class = EventData
    data = event_data_class(json.dumps(event, ensure_ascii=True, allow_nan=False, separators=(",", ":")))
    data.content_type = "application/json"
    data.message_id = event["EventId"]
    batch = producer.create_batch(partition_key=event["OrderKey"])
    batch.add(data)
    producer.send_batch(batch, timeout=30)


def stream_to_eventstream(config, connection_string, *, run_id=None):
    from azure.eventhub import EventHubProducerClient, TransportType
    from azure.eventhub.exceptions import EventHubError

    simulation = SalesSimulation(config, run_id=run_id)
    producer = EventHubProducerClient.from_connection_string(
        connection_string, transport_type=TransportType.AmqpOverWebsocket,
        retry_total=3, retry_backoff_factor=0.8, logging_enable=False,
    )
    sent = 0
    events = simulation.events(realtime=True)
    try:
        with producer:
            for event in events:
                try:
                    publish_event(producer, event)
                except EventHubError:
                    raise RuntimeError(
                        f"Eventstream send failed for EventId={event['EventId']}. "
                        "Delivery may be uncertain. Deduplicate by EventId; check endpoint, permissions, and network."
                    ) from None
                sent += 1
                if sent % 25 == 0:
                    print(f"Acknowledged {sent} events; current type: {event['EventType']}")
    finally:
        events.close()
        print(json.dumps({"events_acknowledged": sent, **simulation.stats}, indent=2))
    return simulation.stats
