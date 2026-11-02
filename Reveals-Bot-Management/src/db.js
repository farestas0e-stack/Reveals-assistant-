const fs=require('node:fs'),path=require('node:path'),Database=require('better-sqlite3'),c=require('./config');
fs.mkdirSync(path.dirname(path.resolve(c.DATABASE_PATH)),{recursive:true});
const db=new Database(path.resolve(c.DATABASE_PATH));db.pragma('journal_mode=WAL');db.pragma('foreign_keys=ON');db.exec(fs.readFileSync(path.join(__dirname,'schema.sql'),'utf8'));module.exports=db;
