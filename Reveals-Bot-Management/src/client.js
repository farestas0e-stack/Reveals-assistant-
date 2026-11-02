const {Client,GatewayIntentBits,Partials}=require('discord.js');
module.exports=new Client({intents:[GatewayIntentBits.Guilds,GatewayIntentBits.GuildMembers,GatewayIntentBits.GuildModeration,GatewayIntentBits.GuildMessages],partials:[Partials.Message,Partials.Channel,Partials.GuildMember,Partials.User]});
