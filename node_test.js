setInterval(() => console.log('running...'), 1000); 
process.on('SIGBREAK', () => { 
    console.log('got SIGBREAK'); 
    setTimeout(()=>process.exit(0), 1000); 
}); 
process.on('SIGINT', () => { 
    console.log('got SIGINT'); 
    setTimeout(()=>process.exit(0), 1000); 
});
