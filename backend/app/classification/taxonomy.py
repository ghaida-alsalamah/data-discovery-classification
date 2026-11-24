from dataclasses import dataclass


@dataclass(frozen=True)
class SemanticType:
    category: str
    english: str
    arabic: str
    aliases: tuple[str, ...]


def entry(category, english, arabic, aliases):
    return SemanticType(category, english, arabic, tuple(aliases.split("|")))


TYPES = {
    "person_name": entry("person_name", "full given and family name of a person", "الاسم الكامل للشخص", "full name|person name|first name|last name|customer name|employee name|اسم الشخص|الاسم الكامل|اسم العميل|اسم الموظف"),
    "saudi_national_id": entry("saudi_national_id", "Saudi citizen national identity number", "رقم الهوية الوطنية السعودية", "national id|national identity|هوية وطنية|رقم الهوية"),
    "saudi_residency_id": entry("saudi_residency_id", "Saudi resident iqama identification number", "رقم إقامة المقيم في السعودية", "residency id|iqama|رقم الإقامة|الإقامة"),
    "phone_number": entry("phone_number", "telephone contact or mobile phone number", "رقم الهاتف أو الجوال", "phone number|phone|mobile|telephone|هاتف|جوال"),
    "email_address": entry("email_address", "electronic mail address for contacting someone", "عنوان البريد الإلكتروني", "email address|email|work email|بريد إلكتروني"),
    "saudi_iban": entry("saudi_iban", "Saudi international bank account number IBAN", "رقم الحساب المصرفي الدولي السعودي الآيبان", "iban|bank account|آيبان"),
    "location": entry("location", "city or geographic location of a place", "المدينة أو الموقع الجغرافي", "location|موقع"),
    "city": entry("location", "city municipality or office location", "اسم المدينة أو مقر المكتب", "city|office|مدينة"),
    "service_region": entry("location", "geographic region where a service is used", "المنطقة الجغرافية لاستخدام الخدمة", "region|region code|service region|منطقة"),
    "date": entry("date", "calendar date or timestamp for an event", "تاريخ أو وقت وقوع الحدث", "date|timestamp|joined on|opened on|closed on|paid on|تاريخ"),
    "record_id": entry("record_id", "primary key or unique record identifier", "المفتاح الأساسي أو معرف السجل", "id|record id|primary key|معرف السجل"),
    "reference_id": entry("reference_id", "foreign key referring to a related record", "مرجع إلى سجل آخر أو مفتاح خارجي", "reference id|foreign key|مفتاح خارجي"),
    "service_code": entry("service_code", "catalog service or product code", "رمز خدمة في دليل الخدمات", "service code|product code|رمز الخدمة"),
    "financial_amount": entry("financial_amount", "monetary amount in a financial record", "مبلغ مالي في سجل مالي", "amount|value sar|مبلغ"),
    "transaction_amount": entry("financial_amount", "transaction purchase monetary amount", "قيمة مبلغ المعاملة", "transaction amount|مبلغ المعاملة"),
    "payment_amount": entry("financial_amount", "payment monetary amount", "المبلغ المدفوع", "payment amount|مبلغ الدفع"),
    "tax_amount": entry("financial_amount", "monetary tax amount", "مبلغ الضريبة", "tax|tax amount|ضريبة"),
    "salary": entry("salary", "employee salary or compensation amount", "راتب الموظف أو الأجر", "salary|wage|compensation|راتب"),
    "price": entry("price", "price or recurring fee for a product or service", "سعر المنتج أو رسوم الخدمة", "price|fee|monthly fee|سعر|رسوم"),
    "currency_code": entry("currency", "monetary currency code such as SAR or ISO currency", "رمز العملة النقدية", "currency|currency code|عملة"),
    "status": entry("status", "record state or workflow status", "حالة السجل أو سير العمل", "status|state|حالة"),
    "transaction_status": entry("status", "processing or settlement state of a transaction", "حالة معالجة المعاملة أو تسويتها", "transaction status|حالة المعاملة"),
    "payment_status": entry("status", "payment completion or settlement status", "حالة اكتمال الدفع أو التسوية", "payment status|حالة الدفع"),
    "category": entry("category", "classification category or grouping", "فئة التصنيف أو المجموعة", "category|type|فئة"),
    "customer_segment": entry("category", "classification segment for a customer", "شريحة العميل", "segment|customer segment|شريحة"),
    "department": entry("category", "organizational department or division", "القسم الإداري في المؤسسة", "department|division|قسم"),
    "job_title": entry("category", "employee position or job title", "المسمى الوظيفي للموظف", "job title|title|مسمى وظيفي"),
    "service_category": entry("category", "catalog category for a service", "فئة الخدمة في الدليل", "service category|فئة الخدمة"),
    "service_name": entry("free_text", "display name of a service", "اسم الخدمة المعروض", "service name|اسم الخدمة"),
    "sales_channel": entry("category", "sales channel used for a purchase", "قناة المبيعات المستخدمة", "channel|sales channel|قناة البيع"),
    "payment_method": entry("category", "method or instrument used to pay", "طريقة أو وسيلة الدفع", "method|payment method|طريقة الدفع"),
    "ticket_topic": entry("category", "support request topic or subject", "موضوع تذكرة الدعم", "subject|topic|ticket topic|موضوع"),
    "ticket_priority": entry("category", "priority level for a support ticket", "مستوى أولوية تذكرة الدعم", "priority|ticket priority|أولوية"),
    "device_category": entry("category", "type of device used by the user", "نوع الجهاز المستخدم", "device|device type|جهاز"),
    "boolean_flag": entry("boolean_flag", "true or false indicator or boolean flag", "مؤشر منطقي صحيح أو خطأ", "active|available|boolean|flag|enabled|نشط|متاح"),
    "count": entry("count", "integer count of occurrences or items", "عدد مرات الحدوث أو العناصر", "count|quantity|عدد"),
    "session_count": entry("count", "number of user sessions", "عدد جلسات المستخدم", "sessions|session count|عدد الجلسات"),
    "duration_minutes": entry("duration", "elapsed time or duration in minutes", "المدة الزمنية بالدقائق", "minutes|duration|مدة|دقائق"),
    "free_text": entry("free_text", "unstructured written text such as notes or comments", "نص حر غير منظم مثل الملاحظات والتعليقات", "notes|comments|description|نص|ملاحظات"),
    "unknown": entry("unknown", "insufficient evidence for a semantic type", "أدلة غير كافية لتحديد النوع", "unknown|غير معروف"),
}

DOMAINS = {
    "customer": ("customer account client subscriber", "العملاء والمشتركون", ("customer", "client", "subscriber")),
    "workforce": ("employee staff personnel human resources", "الموظفون والموارد البشرية", ("employee", "staff", "personnel", "workforce")),
    "catalog": ("service product catalog and offerings", "دليل الخدمات والمنتجات", ("service", "product", "catalog")),
    "commerce": ("commercial transaction purchase order sales", "المعاملات التجارية والمبيعات", ("transaction", "order", "purchase", "sales")),
    "finance": ("payment billing finance ledger invoice", "المدفوعات والفواتير والمالية", ("payment", "billing", "finance", "invoice", "ledger")),
    "support": ("customer support help desk ticket", "تذاكر الدعم وخدمة العملاء", ("support", "ticket", "helpdesk")),
    "operations": ("service consumption usage operational activity", "استخدام الخدمات والعمليات", ("usage", "operations", "activity", "telemetry")),
}
