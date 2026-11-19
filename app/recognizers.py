# Spec: docs/specs/pii-engine.md
from __future__ import annotations

import re
from typing import Iterable, List, Optional

from presidio_analyzer import EntityRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import NlpArtifacts
from presidio_analyzer.predefined_recognizers import PhoneRecognizer, SpacyRecognizer

# Ecuadorian and regional phone recognition defaults.
PHONE_SUPPORTED_REGIONS = ("EC", "US", "GB", "DE", "FR", "IL", "IN", "CA", "BR", "ES")

EN_PHONE_CONTEXT = [
    "phone",
    "number",
    "telephone",
    "cell",
    "cellphone",
    "mobile",
    "call",
    "whatsapp",
    "tel",
]

ES_PHONE_CONTEXT = [
    "tel",
    "teléfono",
    "telefono",
    "tlf",
    "cel",
    "celular",
    "móvil",
    "movil",
    "whatsapp",
    "wsp",
    "fono",
    "llamar",
    "phone",
    "telephone",
    "cell",
    "mobile",
]

_PLACEHOLDER_TOKEN_RE = re.compile(r"^\[[A-Z_]+_[0-9a-f]{8}\]$")

# Clause splitting that preserves common Spanish/English abbreviations.
_ABBREV_DOT_RE = re.compile(
    r"(?i)\b(?:c\.i|r\.u\.c|tel|tlf|cel|nro|no|cta|núm|num)\."
)
_CLAUSE_BREAK_RE = re.compile(r"[,;\n\r!?]|\.(?:\s|$)")

_CEDULA_CONTEXT_RE = re.compile(
    r"(?i)(?:\bc[ée]dula\b|\bc\.i\.(?!\w)|\bci\b|\bidentidad\b|\bidentificaci[óo]n\b|\bdocumento\b|\bdni\b)"
)
_PHONE_CONTEXT_RE = re.compile(
    r"(?i)(?:\+593\b|\btel\.?(?!\w)|\btel[ée]fono\b|\btlf\.?(?!\w)|\bcel\.?(?!\w)|"
    r"\bcelular\b|\bm[óo]vil\b|\bwhatsapp\b|\bwsp\b|\bfono\b|\bphone\b|\bmobile\b|\bcell\b|\bcall\b)"
)
_ACCOUNT_CONTEXT_RE = re.compile(
    r"(?i)(?:\bcuenta\b|\bcta\.?(?!\w)|\biban\b|\baccount\b|\bacct\.?(?!\w))"
)
_RUC_CONTEXT_RE = re.compile(
    r"(?i)(?:\br\.u\.c\.(?!\w)|\bruc\b|\bcontribuyente\b|\btributari[oa]\b|\bsri\b)"
)

_CEDULA_CANDIDATE_RE = re.compile(r"(?<![\d-])(?P<val>\d{9}-?\d)(?![\d-])")
_RUC_CANDIDATE_RE = re.compile(r"(?<![\d-])(?P<val>\d{10}(?:-\d{3}|\d{3}))(?![\d-])")

_BANK_ACCOUNT_RE = re.compile(
    r"(?i)"
    r"(?:"
    r"\b(?:"
    r"(?:n[úu]mero|nro\.?|n[°º]|no\.?|num\.?|#)[ \t]+de[ \t]+(?:cuenta|cta\.?)"
    r"|cuenta(?:[ \t]+(?:de[ \t]+(?:ahorros?|ahorro[ \t]+(?:ordinario|programado|infantil)|cooperativa)"
    r"|ahorro[ \t]+(?:ordinario|programado|infantil)|ahorros?|corriente|bancaria|personal|empresarial))?"
    r"|cta\.?(?:[ \t]+(?:de[ \t]+ahorros?|ahorros?|cte\.?|corriente|bancaria))?"
    r"|(?:bank|checking|savings)[ \t]+account(?:[ \t]+(?:number|no\.?|#))?"
    r"|account(?:[ \t]+(?:number|no\.?|#))?"
    r"|acct\.?(?:[ \t]*(?:number|no\.?|#))?"
    r")"
    r"(?:[ \t]*(?:n[úu]mero|nro\.?|n[°º]|no\.?|#))?"
    r"(?:[ \t]*[:=][ \t]*|[ \t]+-[ \t]+|[ \t]+(?:es|is)(?:[ \t]*[:=])?[ \t]+|[ \t]+)"
    r"(?<![+$€£\dA-Za-z])(?P<acct>\d{2,6}(?:-\d{2,6})+|\d{6,20})(?![\dA-Za-z])"
    r"|"
    r"\biban(?:[ \t]*[:=][ \t]*|[ \t]+-[ \t]+|[ \t]+(?:es|is)(?:[ \t]*[:=])?[ \t]+|[ \t]+)"
    r"(?P<iban>[A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]){10,30}|\d{6,20})(?![\dA-Za-z])"
    r")"
)

_NON_ACCOUNT_SUFFIX_RE = re.compile(
    r"(?i)^\s*(?:usd|us\$|\$|d[óo]lares|euros|€|meses|d[íi]as|a[ñn]os|%|por\s*ciento)\b"
)

_SECRET_CREDENTIAL_RE = re.compile(
    r"(?i)\b(?:"
    r"(?:clave|contrase(?:ñ|n)a)"
    r"(?:\s+(?:de\s+acceso|de\s+ingreso|de\s+seguridad|del?\s+(?:cajero|la\s+tarjeta)|"
    r"web|m[óo]vil|temporal|din[áa]mica|secreta|personal|bancaria|transaccional))?"
    r"|pin(?:\s+(?:de\s+seguridad|de\s+acceso|del?\s+(?:cajero|la\s+tarjeta)|temporal|code))?"
    r"|c[óo]digo\s+(?:de\s+seguridad|de\s+verificaci[óo]n|temporal|otp|sms)"
    r"|otp"
    r"|password|passcode|security\s+code|verification\s+code|one-time\s+password"
    r")"
    r"(?:\s*(?::|=)|\s+(?:es|is)(?:\s*[:=])?)\s*"
    r"(?P<raw>\"[^\s\"][^\"]{1,62}[^\s\"]\"|'[^\s'][^']{1,62}[^\s']'|[^\s,;]+)"
)

_SECRET_NON_VALUE_WORDS = frozenset(
    {
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "unos",
        "unas",
        "de",
        "del",
        "en",
        "para",
        "por",
        "con",
        "sin",
        "muy",
        "más",
        "mas",
        "no",
        "si",
        "sí",
        "que",
        "como",
        "mi",
        "tu",
        "su",
        "este",
        "esta",
        "ese",
        "esa",
        "obligatoria",
        "obligatorio",
        "necesaria",
        "necesario",
        "requerida",
        "requerido",
        "personal",
        "confidencial",
        "privada",
        "privado",
        "secreta",
        "secreto",
        "incorrecta",
        "incorrecto",
        "inválida",
        "invalida",
        "inválido",
        "invalido",
        "válida",
        "valida",
        "válido",
        "valido",
        "nueva",
        "nuevo",
        "diferente",
        "distinta",
        "misma",
        "mismo",
        "temporal",
        "expirada",
        "caducada",
        "bloqueada",
        "bloqueado",
        "correcta",
        "correcto",
        "segura",
        "seguro",
        "fácil",
        "facil",
        "difícil",
        "dificil",
        "the",
        "and",
        "not",
        "very",
        "required",
        "optional",
        "invalid",
        "valid",
        "wrong",
        "incorrect",
        "expired",
        "blocked",
        "confidential",
        "private",
        "new",
        "same",
        "different",
    }
)

# Spanish NER false-positive filters (greetings, sentence-initial verbs,
# generic financial/banking vocabulary mis-tagged as PER/ORG by es_core_news_sm).
_ES_NON_PII_SINGLE_WORDS = frozenset(
    {
        "hola",
        "buenos",
        "buenas",
        "saludos",
        "gracias",
        "disculpe",
        "disculpa",
        "perdón",
        "perdon",
        "estimado",
        "estimada",
        "estimados",
        "estimadas",
        "atentamente",
        "cordialmente",
        "bienvenido",
        "bienvenida",
        "bienvenidos",
        "necesito",
        "quiero",
        "quisiera",
        "tengo",
        "deseo",
        "solicito",
        "consulto",
        "busco",
        "requiero",
        "puedo",
        "podría",
        "podria",
        "podrían",
        "podrian",
        "ayuda",
        "ayúdeme",
        "ayudeme",
        "indíqueme",
        "indiqueme",
        "información",
        "informacion",
        "consulta",
        "pregunta",
        "cuál",
        "cual",
        "cuáles",
        "cuales",
        "qué",
        "que",
        "cómo",
        "como",
        "dónde",
        "donde",
        "cuándo",
        "cuando",
        "cuánto",
        "cuanto",
        "quién",
        "quien",
        "abrir",
        "consultar",
        "activar",
        "ver",
        "saber",
        "simulador",
        "crédito",
        "credito",
        "créditos",
        "creditos",
        "ahorro",
        "ahorros",
        "cuenta",
        "cuentas",
        "depósito",
        "deposito",
        "préstamo",
        "prestamo",
        "préstamos",
        "prestamos",
        "tarjeta",
        "tarjetas",
        "banca",
        "saldo",
        "tasa",
        "tasas",
        "cuota",
        "cuotas",
        "plazo",
        "fijo",
        "socio",
        "socios",
        "cliente",
        "clientes",
        "titular",
        "agencia",
        "sucursal",
        "requisitos",
        "estado",
        "servicio",
        "servicios",
        "producto",
        "productos",
        "cédula",
        "cedula",
        "ci",
        "dni",
        "ruc",
        "iban",
        "cta",
        "nro",
        "clave",
        "contraseña",
        "contrasena",
        "password",
        "pin",
        "otp",
        "tel",
        "teléfono",
        "telefono",
        "cel",
        "celular",
        "móvil",
        "movil",
        "whatsapp",
        "wsp",
        "correo",
        "email",
    }
)

_ES_BANKING_GENERIC_TERMS = _ES_NON_PII_SINGLE_WORDS | frozenset(
    {
        "de",
        "del",
        "al",
        "a",
        "en",
        "y",
        "e",
        "o",
        "u",
        "para",
        "por",
        "con",
        "sin",
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "mi",
        "tu",
        "su",
        "días",
        "dias",
        "tardes",
        "noches",
        "muchas",
        "favor",
        "ordinario",
        "ordinaria",
        "programado",
        "programada",
        "infantil",
        "juvenil",
        "corriente",
        "hipotecario",
        "hipotecaria",
        "consumo",
        "microempresa",
        "microcrédito",
        "microcredito",
        "educativo",
        "educativa",
        "personal",
        "comercial",
        "productivo",
        "productiva",
        "inmobiliario",
        "vehicular",
        "virtual",
        "móvil",
        "movil",
        "débito",
        "debito",
        "línea",
        "linea",
        "inversión",
        "inversion",
        "póliza",
        "poliza",
        "certificado",
        "seguro",
        "seguros",
        "cheque",
        "chequera",
        "remesas",
        "giros",
        "pagos",
        "transferencia",
        "transferencias",
        "cajero",
        "interés",
        "interes",
        "seguridad",
        "acceso",
        "contacto",
        "atención",
        "atencion",
        "hazte",
        "hoy",
        "back",
        "to",
        "aaa",
    }
)

_ES_NON_NOUN_POS = frozenset(
    {"VERB", "AUX", "ADV", "INTJ", "PRON", "DET", "ADP", "SCONJ", "CCONJ", "PUNCT", "SYM"}
)

_ES_PERSON_LEADING_PREFIX_RE = re.compile(
    r"^(?:"
    r"(?:(?:hola|buenos[ \t]+d[íi]as|buenas[ \t]+(?:tardes|noches)|saludos|estimad[oa]s?)(?:[ \t]*,)?[ \t]+)*"
    r"(?:me[ \t]+llamo|mi[ \t]+nombre(?:[ \t]+completo)?[ \t]+es|soy|"
    r"(?:nombre(?:[ \t]+completo)?|cliente|titular|socio|contacto|solicitante|beneficiario)[ \t]*[:=])[ \t]+"
    r"|(?:hola|buenos[ \t]+d[íi]as|buenas[ \t]+(?:tardes|noches)|saludos|estimad[oa]s?)(?:[ \t]*,)?[ \t]+"
    r")",
    re.IGNORECASE,
)

# Name token: Title-Case alphabetic word (supporting Spanish diacritics).
_ES_NAME_WORD = r"[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]{1,24}"
_ES_NAME_SEQ = (
    rf"{_ES_NAME_WORD}"
    rf"(?:[ \t]+(?:(?:de(?:[ \t]+la|[ \t]+los|[ \t]+las)?|del)[ \t]+)?{_ES_NAME_WORD}){{1,3}}"
)

_ES_PERSON_CUE_RE = re.compile(
    r"(?:"
    r"\b(?:[Mm]e[ \t]+llamo|[Mm]i[ \t]+nombre(?:[ \t]+completo)?[ \t]+es|[Ss]oy)[ \t]+"
    r"|\b(?:[Nn]ombre(?:[ \t]+completo)?|[Tt]itular|[Cc]liente|[Ss]olicitante|[Bb]eneficiario|[Cc]ontacto)[ \t]*[:=][ \t]*"
    r"|\b(?:[Aa]tentamente|[Ss]aludos|[Cc]ordialmente)[ \t]*,[ \t]*"
    r"|\b[Ee]stimad[oa][ \t]+"
    r")"
    rf"(?P<name>{_ES_NAME_SEQ})\b"
)

_ES_NON_NAME_WORDS = _ES_BANKING_GENERIC_TERMS | frozenset(
    {
        "cooperativa",
        "banco",
        "financiera",
        "corporación",
        "corporacion",
        "empresa",
        "compañía",
        "compania",
        "sociedad",
        "fundación",
        "fundacion",
        "instituto",
        "ministerio",
        "municipio",
        "gobierno",
        "superintendencia",
        "ecuador",
        "quito",
        "guayaquil",
        "cuenca",
        "ambato",
        "ibarra",
        "tulcán",
        "tulcan",
        "san",
        "santa",
        "santo",
    }
)

# Common Spanish/Ecuadorian given names used ONLY to rescue spaCy MISC spans
# that es_core_news_sm fails to label as PER (e.g. "María José López").
_COMMON_ES_GIVEN_NAMES = frozenset(
    {
        "adriana",
        "alberto",
        "alejandra",
        "alejandro",
        "alexandra",
        "alfonso",
        "alicia",
        "ana",
        "andrea",
        "andrés",
        "andres",
        "ángel",
        "angel",
        "ángela",
        "angela",
        "angélica",
        "angelica",
        "antonio",
        "arturo",
        "beatriz",
        "blanca",
        "bolívar",
        "bolivar",
        "byron",
        "camila",
        "carla",
        "carlos",
        "carmen",
        "carolina",
        "catalina",
        "cecilia",
        "césar",
        "cesar",
        "christian",
        "cinthya",
        "claudia",
        "cristian",
        "cristina",
        "daniel",
        "daniela",
        "david",
        "diana",
        "diego",
        "doris",
        "edison",
        "eduardo",
        "edwin",
        "elena",
        "elizabeth",
        "enrique",
        "erika",
        "esteban",
        "estefanía",
        "estefania",
        "evelyn",
        "fabián",
        "fabian",
        "fanny",
        "fernanda",
        "fernando",
        "francisco",
        "freddy",
        "gabriel",
        "gabriela",
        "galo",
        "geovanny",
        "gloria",
        "grace",
        "guillermo",
        "gustavo",
        "héctor",
        "hector",
        "henry",
        "hernán",
        "hernan",
        "hugo",
        "irene",
        "isabel",
        "iván",
        "ivan",
        "jacqueline",
        "jaime",
        "janeth",
        "javier",
        "jenny",
        "jessica",
        "jhon",
        "jimmy",
        "johanna",
        "jonathan",
        "jorge",
        "josé",
        "jose",
        "joselyn",
        "juan",
        "julia",
        "julio",
        "karina",
        "katherine",
        "kevin",
        "kleber",
        "laura",
        "leonardo",
        "liliana",
        "lina",
        "lorena",
        "lourdes",
        "lucía",
        "lucia",
        "luis",
        "luisa",
        "magdalena",
        "manuel",
        "marcela",
        "marcelo",
        "marcia",
        "marco",
        "margarita",
        "maría",
        "maria",
        "mariana",
        "maribel",
        "mario",
        "marisol",
        "maritza",
        "marta",
        "martha",
        "mateo",
        "mauricio",
        "mayra",
        "mercedes",
        "miguel",
        "milton",
        "miriam",
        "mónica",
        "monica",
        "myriam",
        "nadia",
        "nancy",
        "natalia",
        "nelson",
        "nicolás",
        "nicolas",
        "norma",
        "olga",
        "omar",
        "orlando",
        "óscar",
        "oscar",
        "pablo",
        "paola",
        "patricia",
        "patricio",
        "paula",
        "pedro",
        "pilar",
        "priscila",
        "rafael",
        "ramiro",
        "ramón",
        "ramon",
        "raúl",
        "raul",
        "rené",
        "rene",
        "ricardo",
        "roberto",
        "rocío",
        "rocio",
        "rodrigo",
        "rommel",
        "rosa",
        "rubén",
        "ruben",
        "sandra",
        "santiago",
        "sebastián",
        "sebastian",
        "segundo",
        "sergio",
        "silvia",
        "sofía",
        "sofia",
        "sonia",
        "susana",
        "tatiana",
        "teresa",
        "valentina",
        "valeria",
        "vanessa",
        "verónica",
        "veronica",
        "víctor",
        "victor",
        "vinicio",
        "viviana",
        "walter",
        "washington",
        "william",
        "wilson",
        "xavier",
        "yadira",
        "yolanda",
    }
)


def is_valid_ec_cedula(value: str) -> bool:
    """Validate a 10-digit Ecuadorian cédula (province 01..24 or 30, 3rd digit 0..5, mod-10)."""
    if "-" in value:
        if len(value) != 11 or value[9] != "-":
            return False
        digits = value[:9] + value[10]
    else:
        digits = value

    if len(digits) != 10 or not digits.isdigit():
        return False

    province = int(digits[:2])
    if not (1 <= province <= 24 or province == 30):
        return False

    third = int(digits[2])
    if third > 5:
        return False

    coeffs = (2, 1, 2, 1, 2, 1, 2, 1, 2)
    total = 0
    for ch, coef in zip(digits[:9], coeffs):
        prod = int(ch) * coef
        total += prod - 9 if prod >= 10 else prod
    rem = total % 10
    expected = 0 if rem == 0 else 10 - rem
    return expected == int(digits[9])


def is_valid_ec_ruc(value: str) -> bool:
    """Validate a 13-digit Ecuadorian RUC (natural person, private entity, or public entity)."""
    if "-" in value:
        if len(value) != 14 or value[10] != "-":
            return False
        digits = value[:10] + value[11:]
    else:
        digits = value

    if len(digits) != 13 or not digits.isdigit():
        return False

    province = int(digits[:2])
    if not (1 <= province <= 24 or province == 30):
        return False

    establishment = int(digits[10:13])
    if not (1 <= establishment <= 999):
        return False

    third = int(digits[2])
    if 0 <= third <= 5:
        return is_valid_ec_cedula(digits[:10])

    if third == 9:
        coeffs = (4, 3, 2, 7, 6, 5, 4, 3, 2)
        total = sum(int(ch) * coef for ch, coef in zip(digits[:9], coeffs))
        rem = total % 11
        expected = 0 if rem == 0 else 11 - rem
        return expected == int(digits[9])

    if third == 6:
        if digits[9] != "0":
            return False
        coeffs = (3, 2, 7, 6, 5, 4, 3, 2)
        total = sum(int(ch) * coef for ch, coef in zip(digits[:8], coeffs))
        rem = total % 11
        expected = 0 if rem == 0 else 11 - rem
        return expected == int(digits[8])

    return False


def _local_preceding_clause(text: str, start: int, max_chars: int = 60) -> str:
    window = text[max(0, start - max_chars) : start]
    masked = _ABBREV_DOT_RE.sub(lambda m: " " * len(m.group(0)), window)
    last_break = -1
    for m in _CLAUSE_BREAK_RE.finditer(masked):
        last_break = m.end()
    return window[last_break:] if last_break != -1 else window


def _local_following_clause(text: str, end: int, max_chars: int = 25) -> str:
    window = text[end : min(len(text), end + max_chars)]
    masked = _ABBREV_DOT_RE.sub(lambda m: " " * len(m.group(0)), window)
    m = _CLAUSE_BREAK_RE.search(masked)
    return window[: m.start()] if m else window


def _last_match_end(pattern: re.Pattern[str], segment: str) -> int:
    pos = -1
    for m in pattern.finditer(segment):
        pos = m.end()
    return pos


def _first_match_start(pattern: re.Pattern[str], segment: str) -> int:
    m = pattern.search(segment)
    return m.start() if m else -1


def build_phone_recognizer(language: str) -> PhoneRecognizer:
    """Create a PhoneRecognizer with Ecuadorian region and language-appropriate context."""
    context = ES_PHONE_CONTEXT if language == "es" else EN_PHONE_CONTEXT
    return PhoneRecognizer(
        supported_language=language,
        supported_regions=PHONE_SUPPORTED_REGIONS,
        context=list(context),
    )


class EcCedulaRecognizer(EntityRecognizer):
    """Detects valid 10-digit Ecuadorian cédula numbers with phone/account disambiguation."""

    def __init__(self, supported_language: str = "es") -> None:
        super().__init__(
            supported_entities=["EC_CEDULA"],
            supported_language=supported_language,
            name="EcCedulaRecognizer",
        )

    def load(self) -> None:  # noqa: D102
        pass

    def analyze(
        self,
        text: str,
        entities: List[str],
        nlp_artifacts: Optional[NlpArtifacts] = None,
    ) -> List[RecognizerResult]:
        if "EC_CEDULA" not in entities:
            return []

        results: List[RecognizerResult] = []
        for match in _CEDULA_CANDIDATE_RE.finditer(text):
            val = match.group("val")
            if not is_valid_ec_cedula(val):
                continue

            start, end = match.start("val"), match.end("val")
            prec = _local_preceding_clause(text, start)
            ced_pos = _last_match_end(_CEDULA_CONTEXT_RE, prec)
            phone_pos = _last_match_end(_PHONE_CONTEXT_RE, prec)
            acct_pos = _last_match_end(_ACCOUNT_CONTEXT_RE, prec)

            # Check immediate trailing label if preceding clause had no signal (e.g. "0958901233 (cédula)").
            if ced_pos == -1 and phone_pos == -1 and acct_pos == -1:
                foll = _local_following_clause(text, end)
                f_ced = _first_match_start(_CEDULA_CONTEXT_RE, foll)
                f_phone = _first_match_start(_PHONE_CONTEXT_RE, foll)
                f_acct = _first_match_start(_ACCOUNT_CONTEXT_RE, foll)
                # Convert earliest trailing distance into comparable recency (higher wins).
                if f_ced != -1:
                    ced_pos = 1000 - f_ced
                if f_phone != -1:
                    phone_pos = 1000 - f_phone
                if f_acct != -1:
                    acct_pos = 1000 - f_acct

            if ced_pos >= 0 and ced_pos >= phone_pos and ced_pos >= acct_pos:
                score = 0.92
            elif phone_pos >= 0 and phone_pos > ced_pos and phone_pos >= acct_pos:
                # Explicit phone context (tel, celular, whatsapp, +593, ...) lets PHONE_NUMBER win.
                continue
            elif acct_pos >= 0 and acct_pos > ced_pos:
                score = 0.25
            else:
                score = 0.65

            results.append(
                RecognizerResult(
                    entity_type="EC_CEDULA",
                    start=start,
                    end=end,
                    score=score,
                )
            )
        return results


class EcRucRecognizer(EntityRecognizer):
    """Detects valid 13-digit Ecuadorian RUC numbers (natural, private, public)."""

    def __init__(self, supported_language: str = "es") -> None:
        super().__init__(
            supported_entities=["EC_RUC"],
            supported_language=supported_language,
            name="EcRucRecognizer",
        )

    def load(self) -> None:  # noqa: D102
        pass

    def analyze(
        self,
        text: str,
        entities: List[str],
        nlp_artifacts: Optional[NlpArtifacts] = None,
    ) -> List[RecognizerResult]:
        if "EC_RUC" not in entities:
            return []

        results: List[RecognizerResult] = []
        for match in _RUC_CANDIDATE_RE.finditer(text):
            val = match.group("val")
            if not is_valid_ec_ruc(val):
                continue

            start, end = match.start("val"), match.end("val")
            prec = _local_preceding_clause(text, start)
            ruc_pos = _last_match_end(_RUC_CONTEXT_RE, prec)
            acct_pos = _last_match_end(_ACCOUNT_CONTEXT_RE, prec)

            if ruc_pos >= 0 and ruc_pos >= acct_pos:
                score = 0.95
            elif acct_pos >= 0 and acct_pos > ruc_pos:
                score = 0.50
            else:
                score = 0.85

            results.append(
                RecognizerResult(
                    entity_type="EC_RUC",
                    start=start,
                    end=end,
                    score=score,
                )
            )
        return results


class BankAccountRecognizer(EntityRecognizer):
    """Contextual recognizer for bank/cooperative account numbers and IBANs.

    Masks only the account identifier token span (never the triggering keyword),
    beats PHONE_NUMBER in account context, and avoids monetary/duration false positives.
    """

    def __init__(self, supported_language: str = "es") -> None:
        super().__init__(
            supported_entities=["BANK_ACCOUNT"],
            supported_language=supported_language,
            name="BankAccountRecognizer",
        )

    def load(self) -> None:  # noqa: D102
        pass

    def analyze(
        self,
        text: str,
        entities: List[str],
        nlp_artifacts: Optional[NlpArtifacts] = None,
    ) -> List[RecognizerResult]:
        if "BANK_ACCOUNT" not in entities:
            return []

        results: List[RecognizerResult] = []
        for match in _BANK_ACCOUNT_RE.finditer(text):
            if match.group("acct") is not None:
                raw = match.group("acct")
                start, end = match.start("acct"), match.end("acct")
                digits = raw.replace("-", "")
                if not (6 <= len(digits) <= 20 and digits.isdigit()):
                    continue
            elif match.group("iban") is not None:
                raw = match.group("iban")
                start, end = match.start("iban"), match.end("iban")
                compact = re.sub(r"[\s-]", "", raw)
                if compact.isdigit():
                    if not (6 <= len(compact) <= 20):
                        continue
                else:
                    if not (14 <= len(compact) <= 34):
                        continue
            else:
                continue

            if _NON_ACCOUNT_SUFFIX_RE.match(text[end:]):
                continue

            results.append(
                RecognizerResult(
                    entity_type="BANK_ACCOUNT",
                    start=start,
                    end=end,
                    score=0.90,
                )
            )
        return results


class SecretCredentialRecognizer(EntityRecognizer):
    """Contextual recognizer for passwords, PINs, security codes, and OTPs.

    Requires a secret keyword followed by an explicit separator (es/is/:/=)
    and masks only the secret value token span.
    """

    def __init__(self, supported_language: str = "es") -> None:
        super().__init__(
            supported_entities=["SECRET_CREDENTIAL"],
            supported_language=supported_language,
            name="SecretCredentialRecognizer",
        )

    def load(self) -> None:  # noqa: D102
        pass

    def analyze(
        self,
        text: str,
        entities: List[str],
        nlp_artifacts: Optional[NlpArtifacts] = None,
    ) -> List[RecognizerResult]:
        if "SECRET_CREDENTIAL" not in entities:
            return []

        results: List[RecognizerResult] = []
        for match in _SECRET_CREDENTIAL_RE.finditer(text):
            raw = match.group("raw")
            start, end = match.start("raw"), match.end("raw")

            # Strip matching outer quotes so only the inner credential value is masked.
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
                start += 1
                end -= 1
                raw = raw[1:-1]
            else:
                # Trim trailing sentence punctuation while preserving password symbols like !@#$%.
                while raw and raw[-1] in ".,;:)]}":
                    raw = raw[:-1]
                    end -= 1
                while raw and raw[0] in "([{":
                    raw = raw[1:]
                    start += 1

            if len(raw) < 3:
                continue
            if _PLACEHOLDER_TOKEN_RE.fullmatch(raw):
                continue
            # Avoid masking plain Spanish/English prose adjectives like "la clave es obligatoria".
            if raw.isalpha() and raw.islower() and raw in _SECRET_NON_VALUE_WORDS:
                continue

            results.append(
                RecognizerResult(
                    entity_type="SECRET_CREDENTIAL",
                    start=start,
                    end=end,
                    score=0.95,
                )
            )
        return results


def _normalize_words(span_text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü0-9]+", span_text)]


def _is_generic_spanish_non_pii(span_text: str) -> bool:
    stripped = span_text.strip()
    if not stripped or stripped[0] in "¿¡":
        return True
    words = _normalize_words(stripped)
    if not words:
        return True
    if len(words) == 1 and words[0] in _ES_NON_PII_SINGLE_WORDS:
        return True
    if all(w in _ES_BANKING_GENERIC_TERMS for w in words):
        return True
    return False


def _is_plausible_es_person_name(span_text: str) -> bool:
    words = _normalize_words(span_text)
    if len(words) < 2 or len(words) > 5:
        return False
    content_words = [w for w in words if w not in {"de", "del", "la", "los", "las"}]
    if len(content_words) < 2:
        return False
    if any(w in _ES_NON_NAME_WORDS for w in content_words):
        return False
    return True


def _trim_es_person_prefix(text: str, start: int, end: int) -> tuple[int, int]:
    segment = text[start:end]
    # Never let a Spanish PERSON span bleed across a line break.
    nl_pos = segment.find("\n")
    cr_pos = segment.find("\r")
    cut = min(p for p in (nl_pos, cr_pos) if p != -1) if (nl_pos != -1 or cr_pos != -1) else -1
    if cut != -1:
        end = start + cut
        segment = text[start:end].rstrip(" \t")
        end = start + len(segment)
    m = _ES_PERSON_LEADING_PREFIX_RE.match(segment)
    if m and start + m.end() < end:
        start = start + m.end()
    return start, end


class SpanishFilteredSpacyRecognizer(SpacyRecognizer):
    """SpacyRecognizer for Spanish that suppresses common greeting/banking NER false positives."""

    def __init__(self, supported_entities: Optional[List[str]] = None) -> None:
        super().__init__(
            supported_language="es",
            supported_entities=supported_entities or ["PERSON", "ORGANIZATION"],
            name="SpanishFilteredSpacyRecognizer",
        )

    def analyze(
        self,
        text: str,
        entities: List[str],
        nlp_artifacts: Optional[NlpArtifacts] = None,
    ) -> List[RecognizerResult]:
        raw_results = super().analyze(text=text, entities=entities, nlp_artifacts=nlp_artifacts)
        if not raw_results:
            return []

        tokens = list(nlp_artifacts.tokens) if nlp_artifacts and nlp_artifacts.tokens else []
        filtered: List[RecognizerResult] = []
        for res in raw_results:
            start, end = res.start, res.end
            if res.entity_type == "PERSON":
                start, end = _trim_es_person_prefix(text, start, end)

            span_text = text[start:end]
            if _is_generic_spanish_non_pii(span_text):
                continue

            # Reject single-token Spanish PERSON detections whose spaCy POS is non-noun (e.g. VERB "Necesito").
            if res.entity_type == "PERSON" and tokens:
                span_tokens = [
                    tok
                    for tok in tokens
                    if tok.idx >= start and (tok.idx + len(tok.text)) <= end
                ]
                if len(span_tokens) == 1 and span_tokens[0].pos_ in _ES_NON_NOUN_POS:
                    continue

            if start != res.start or end != res.end:
                res = RecognizerResult(
                    entity_type=res.entity_type,
                    start=start,
                    end=end,
                    score=res.score,
                    analysis_explanation=res.analysis_explanation,
                    recognition_metadata=res.recognition_metadata,
                )
            filtered.append(res)
        return filtered


class SpanishPersonContextRecognizer(EntityRecognizer):
    """Supplements es_core_news_sm for Spanish person names introduced by cues or mis-tagged as MISC."""

    def __init__(self) -> None:
        super().__init__(
            supported_entities=["PERSON"],
            supported_language="es",
            name="SpanishPersonContextRecognizer",
        )

    def load(self) -> None:  # noqa: D102
        pass

    def analyze(
        self,
        text: str,
        entities: List[str],
        nlp_artifacts: Optional[NlpArtifacts] = None,
    ) -> List[RecognizerResult]:
        if "PERSON" not in entities:
            return []

        results: List[RecognizerResult] = []

        # 1. Explicit self-introduction / contact cues (e.g. "me llamo María José López").
        for match in _ES_PERSON_CUE_RE.finditer(text):
            name = match.group("name")
            if not _is_plausible_es_person_name(name):
                continue
            results.append(
                RecognizerResult(
                    entity_type="PERSON",
                    start=match.start("name"),
                    end=match.end("name"),
                    score=0.85,
                )
            )

        # 2. Rescue standalone Spanish compound names that es_core_news_sm tags as MISC
        #    (e.g. "María José López") without re-enabling noisy MISC -> ORGANIZATION mapping.
        if nlp_artifacts and nlp_artifacts.entities:
            for ent in nlp_artifacts.entities:
                if ent.label_ != "MISC":
                    continue
                start, end = _trim_es_person_prefix(text, ent.start_char, ent.end_char)
                candidate = text[start:end].strip()
                if not candidate:
                    continue
                # Ensure all non-connector tokens are Title-Case alphabetic and start with a known given name.
                raw_tokens = candidate.split()
                if not (2 <= len(raw_tokens) <= 4):
                    continue
                if raw_tokens[0].lower() not in _COMMON_ES_GIVEN_NAMES:
                    continue
                if not all(
                    (tok.lower() in {"de", "del", "la", "los", "las"} and i > 0)
                    or (tok[0].isupper() and tok.isalpha())
                    for i, tok in enumerate(raw_tokens)
                ):
                    continue
                if not _is_plausible_es_person_name(candidate):
                    continue
                results.append(
                    RecognizerResult(
                        entity_type="PERSON",
                        start=start,
                        end=end,
                        score=0.80,
                    )
                )

        return results


def build_custom_recognizers(language: str) -> Iterable[EntityRecognizer]:
    """Return custom financial/identity recognizers registered for the given language."""
    recognizers: list[EntityRecognizer] = [
        EcCedulaRecognizer(supported_language=language),
        EcRucRecognizer(supported_language=language),
        BankAccountRecognizer(supported_language=language),
        SecretCredentialRecognizer(supported_language=language),
    ]
    if language == "es":
        recognizers.append(SpanishPersonContextRecognizer())
    return recognizers
