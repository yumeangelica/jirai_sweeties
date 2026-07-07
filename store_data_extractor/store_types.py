from typing import Dict, List, NotRequired, Optional, TypedDict, Union

class StoreOptionsDataType(TypedDict):
    base_url: str
    site_main_url: str
    item_container_selector: str
    item_name_selector: str
    item_price_selectors: List[Dict[str, str]]
    item_link_selector: str
    item_image_selector: str
    sold_out_selector: str
    next_page_selector: str
    next_page_selector_text: str
    next_page_attribute: str
    delay_between_requests: int
    encoding: str
    request_headers: NotRequired[Dict[str, str]]
    proxy_url: NotRequired[str]
    fetch_backend: NotRequired[str]
    curl_impersonate: NotRequired[str]
    request_timeout: NotRequired[float]

class StoreConfigDataType(TypedDict):
    name: str
    name_format: str
    options: StoreOptionsDataType
    schedule: Dict[str, Union[List[int], str]]
    run_on_start: NotRequired[bool]

class StoreDataType(TypedDict):
    id: int
    name: str
    initial_fetch: Optional[str]

class ProductPricesDataType(TypedDict, total=False):
    JPY: Optional[float]
    EUR: Optional[float]

class ProductBaseDataType(TypedDict):
    name: str
    product_url: str
    image_url: Optional[str]
    prices: ProductPricesDataType

class ProductDataType(ProductBaseDataType, total=False):
    id: int
    archived: Optional[bool]
