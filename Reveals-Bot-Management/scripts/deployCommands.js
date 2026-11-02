const {REST,Routes}=require('discord.js'),c=require('../src/config');
const commands=require('../src/commands').map(x=>x.data.toJSON());
new REST({version:'10'}).setToken(c.DISCORD_TOKEN).put(Routes.applicationCommands(c.DISCORD_CLIENT_ID),{body:commands}).then(()=>console.log('Registered '+commands.length+' commands.')).catch(e=>{console.error(e);process.exit(1)});
