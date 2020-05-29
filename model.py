from peewee import Model, SqliteDatabase, CharField, ForeignKeyField, DateTimeField, IntegrityError

DB_FILE = 'maps.db'
db = SqliteDatabase(DB_FILE)


class BaseModel(Model):
    class Meta:
        database = db


class Country(BaseModel):
    country_id = CharField(primary_key=True)
    country_name = CharField()
    url = CharField()


class Map(BaseModel):
    country = ForeignKeyField(Country, backref="maps")
    path = CharField(null=True, unique=True)
    url = CharField(null=True, unique=True, index=True)
    date = DateTimeField(null=True)
    md5 = CharField(null=True)
