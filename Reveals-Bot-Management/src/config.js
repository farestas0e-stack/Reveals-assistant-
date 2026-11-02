require('dotenv').config();
const required=['DISCORD_TOKEN','DISCORD_CLIENT_ID','SERVER_A_ID','SERVER_B_ID','SERVER_C_ID','MENTORSHIP_ROLE_ID','MODERATOR_LOG_CHANNEL_ID','RENEWAL_TICKET_CATEGORY_ID','SECURITY_LOG_CHANNEL_ID','RENEWAL_URL'];
const missing=required.filter(k=>!process.env[k]); if(missing.length){console.error('Missing .env values: '+missing.join(', '));process.exit(1);}
module.exports={...process.env,ADMIN_ROLE_IDS:(process.env.ADMIN_ROLE_IDS||'').split(',').map(x=>x.trim()).filter(Boolean),EXPIRATION_CHECK_CRON:process.env.EXPIRATION_CHECK_CRON||'*/15 * * * *',DATABASE_PATH:process.env.DATABASE_PATH||'./data/reveals.sqlite'};
