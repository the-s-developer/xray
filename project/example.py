from datetime import datetime, timedelta
import asyncio
import motor.motor_asyncio
import random
import string

MONGO_URI = "mongodb://mongo:mongo@192.168.99.97:27017"
DB_NAME = "xray"

PROJECT_COUNT = 20  # Kaç tane proje eklensin
SCRIPTS_PER_PROJECT = 3
EXECUTIONS_PER_SCRIPT = 3

PROMPTS = [
    [
        {"role": "system", "content": "Sadece fiyat bilgisini çek."},
        {"role": "user", "content": "Tüm ürünleri listele."}
    ],
    [
        {"role": "user", "content": "Sayfadaki tüm haberleri çek."}
    ],
    [
        {"role": "system", "content": "Bağlantı hatalarını logla."}
    ],
    [
        {"role": "user", "content": "Yalnızca indirimli ürünleri getir."}
    ],
    [
        {"role": "system", "content": "Yalnızca başlık ve özet getir."}
    ]
]

DESCS = [
    "Farklı sitelerden veri toplar.",
    "Fırsatları izler ve raporlar.",
    "Haber başlıklarını çeker.",
    "Ürün puanlarını analiz eder.",
    "Döviz kurunu takip eder.",
    "Kampanya takipçisi.",
    "Yeni gelen ürünleri listeler.",
    "Stok durumunu kontrol eder.",
    "Günün fırsatlarını getirir.",
    "Popüler haberleri yakalar.",
]

def random_id(prefix, length=8):
    return prefix + ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def random_domain():
    domains = ["example.com", "news.com", "shop.com", "kampanya.com", "bank.com", "api.io", "data.net"]
    return random.choice(domains)

def random_prompt():
    return random.choice(PROMPTS)

def random_desc():
    return random.choice(DESCS)

def make_projects(n):
    projects = []
    for i in range(n):
        idx = i + 1
        project_id = f"PRJ{100000+idx}"
        project = {
            "projectId": project_id,
            "projectName": f"Otomatik Proje {idx}",
            "projectDescription": random_desc(),
            "projectStatus": "active",
            "scraperDomain": random_domain(),
            "createdAt": (datetime.utcnow() - timedelta(days=random.randint(0, 40))).isoformat(),
            "updatedAt": datetime.utcnow().isoformat(),
            "prompts": random_prompt(),
            "executionConfig": {"interval": random.choice(["daily", "weekly", "hourly"]), "retries": random.randint(1, 4)}
        }
        projects.append(project)
    return projects

def make_scripts_for_project(project_id, count):
    scripts = []
    base = int(project_id[-3:])
    for i in range(count):
        version = i + 1
        script_id = f"SCR{project_id[-3:]}{chr(65+i)}"
        created = datetime.utcnow() - timedelta(days=random.randint(0, 15))
        scripts.append({
            "scriptId": script_id,
            "projectId": project_id,
            "version": version,
            "code": f"# Sürüm {version} kodu\nprint('Proje {project_id} - Script {version} çalıştı')",
            "createdAt": created.isoformat(),
            "createdBy": "user" if i % 2 == 0 else "llm",
            "generatedByLLM": bool(i % 2),
            "notes": f"Otomatik not {version}"
        })
    return scripts

def make_executions_for_script(project_id, script_id, script_version):
    now = datetime.utcnow() - timedelta(hours=random.randint(0, 48))
    executions = []
    for i in range(EXECUTIONS_PER_SCRIPT):
        is_error = (i == EXECUTIONS_PER_SCRIPT - 1)
        status = "error" if is_error else "success"
        execution_id = f"EXE{script_id[-4:]}{i}"
        executions.append({
            "executionId": execution_id,
            "projectId": project_id,
            "scriptId": script_id,
            "scriptVersion": script_version,
            "status": status,
            "startTime": now.isoformat(),
            "endTime": (now + timedelta(seconds=2)).isoformat(),
            "duration": 2,
            "resultCount": 0 if is_error else random.randint(1, 10),
            "output": "" if is_error else f"{script_id} çıktı sonucu {random.randint(1, 100)}",
            "errorMessage": "Random Error: Hata oluştu" if is_error else "",
            "result": {} if is_error else {"data": [{"foo": "bar", "num": random.randint(1, 100)}]}
        })
    return executions

async def insert_all_sample_data():
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]

    projects = make_projects(PROJECT_COUNT)
    project_ids = [p["projectId"] for p in projects]

    # Projeleri ekle
    for proj in projects:
        exist = await db.projects.find_one({"projectId": proj["projectId"]})
        if not exist:
            await db.projects.insert_one(proj)
            print(f"Proje eklendi: {proj['projectId']}")
        else:
            print(f"Proje zaten var: {proj['projectId']}")

    # Her proje için script ve execution ekle
    for proj in projects:
        scripts = make_scripts_for_project(proj["projectId"], SCRIPTS_PER_PROJECT)
        for script in scripts:
            exist = await db.scripts.find_one({"scriptId": script["scriptId"]})
            if not exist:
                await db.scripts.insert_one(script)
                print(f"Script eklendi: {script['scriptId']}")
            else:
                print(f"Script zaten var: {script['scriptId']}")
            # Her script için execution ekle
            executions = make_executions_for_script(proj["projectId"], script["scriptId"], script["version"])
            for exe in executions:
                exist = await db.executions.find_one({"executionId": exe["executionId"]})
                if not exist:
                    await db.executions.insert_one(exe)
                    print(f"Execution eklendi: {exe['executionId']}")
                else:
                    print(f"Execution zaten var: {exe['executionId']}")

if __name__ == "__main__":
    asyncio.run(insert_all_sample_data())
