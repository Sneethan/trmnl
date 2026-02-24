<style>
  html, body {
  width: 100%;
  height: 100%;
  margin: 0;
  padding: 0;
}

body {
  overflow: hidden; /* prevents scroll bars in the simulator iframe */
}

* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}


.pid-wrapper {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  min-height: 100vh;
  width: 100vw;
  position: relative;
  padding: 16px;
  padding-bottom: 56px; /* reserve space for the bottom title bar */
}

.pid-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  max-width: 100%;
}

.pid-header {
  border-top: 5px solid #555;
  padding: 14px 0;
  margin-bottom: 8px;
}

.pid-next-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.pid-next-dest {
  font-size: 48px;
  font-weight: 500;
  color: #000;
  letter-spacing: -1px;
}

.pid-next-meta {
  font-size: 18px;
  color: #555;
  margin-top: 4px;
}

.pid-countdown {
  background: #000;
  color: #fff;
  padding: 12px 24px;
  font-size: 32px;
  font-weight: 500;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  line-height: 1;
}

.pid-countdown-min {
  font-size: 18px;
  font-weight: 400;
  margin-top: 4px;
}

.pid-stops {
  display: flex;
  border-top: 1px solid #bbb;
  border-bottom: 1px solid #bbb;
  background: #f2f2f2;
  padding: 10px 0;
  padding-left: 16px;  /* Add this */
  gap: 8px;
}
.pid-stop-col {
  flex: 1;
  border-left: 3px solid #555;
  padding-left: 12px;
  padding-right: 8px;
  min-width: 0;
}

.pid-stop-col:first-child {
  padding-left: 16px; /* Extra padding on first column */
}

.pid-stop-col:last-child {
  padding-right: 16px; /* Extra padding on last column */
}

.pid-stop {
  font-size: 14px;
  line-height: 1.7;
  color: #333;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pid-stop.express {
  color: #999;
}

.pid-stop.current {
  background: #555;
  color: #fff;
  padding: 1px 8px;
  margin-left: -12px;
  padding-left: 12px;
  display: inline-block;
}

.pid-upcoming {
  flex: 1;
  padding: 8px 0;
  overflow: hidden;
}

.pid-table {
  width: 100%;
  border-collapse: collapse;
}

.pid-table th {
  text-align: left;
  padding: 8px 8px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #666;
  border-bottom: 2px solid #333;
}

.pid-table th:last-child {
  text-align: right;
}

.pid-table td {
  padding: 10px 10px;
  font-size: 17px;
  border-bottom: 1px solid #ccc;
  vertical-align: middle;
}

.pid-table td:last-child {
  text-align: right;
}

.pid-badge {
  background: #000;
  color: #fff;
  padding: 4px 12px;
  font-size: 15px;
  display: inline-block;
}

.pid-spacer {
  height: 12px;
}
  .title_bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
    margin-bottom: 5px;
    margin-left: 5px;
    margin-right: 5px;
  border-top: 1px solid #ccc;
  background: #f5f5f5;
}

.title_bar .image {
  width: 24px;
  height: 24px;
}

.title_bar .title {
  font-size: 12px;
  font-weight: 600;
}

.title_bar .instance {
  font-size: 12px;
  color: #666;
  margin-left: auto;
}
</style>

<div class="pid-wrapper">
  <div class="pid-content">
    
    <!-- Header with next train -->
    <div class="pid-header">
      <div class="pid-next-row">
        <div class="pid-next-info">
          <div class="pid-next-dest">Cranbourne</div>
          <div class="pid-next-meta">Express · Platform 1</div>
        </div>
        <div class="pid-countdown">
          9:28
          <span class="pid-countdown-min">am</span>
        </div>
      </div>
    </div>
    
    <!-- Stopping pattern -->
    <div class="pid-stops">
      <div class="pid-stop-col">
        <div class="pid-stop current">Melbourne Central</div>
        <div class="pid-stop">Flagstaff</div>
        <div class="pid-stop">Southern Cross</div>
        <div class="pid-stop">Flinders Street</div>
        <div class="pid-stop">Richmond</div>
        <div class="pid-stop">South Yarra</div>
        <div class="pid-stop express">Hawksburn</div>
      </div>
      <div class="pid-stop-col">
        <div class="pid-stop express">Toorak</div>
        <div class="pid-stop express">Armadale</div>
        <div class="pid-stop express">Malvern</div>
        <div class="pid-stop">Caulfield</div>
        <div class="pid-stop">Carnegie</div>
        <div class="pid-stop">Murrumbeena</div>
        <div class="pid-stop">Hughesdale</div>
      </div>
      <div class="pid-stop-col">
        <div class="pid-stop">Oakleigh</div>
        <div class="pid-stop">Huntingdale</div>
        <div class="pid-stop">Clayton</div>
        <div class="pid-stop">Westall</div>
        <div class="pid-stop">Springvale</div>
        <div class="pid-stop">Sandown Park</div>
        <div class="pid-stop">Noble Park</div>
      </div>
      <div class="pid-stop-col">
        <div class="pid-stop">Yarraman</div>
        <div class="pid-stop">Dandenong</div>
        <div class="pid-stop">Lynbrook</div>
        <div class="pid-stop">Merinda Park</div>
        <div class="pid-stop">Cranbourne</div>
      </div>
    </div>
    
    <!-- Upcoming trains table -->
    <div class="pid-upcoming">
      <table class="pid-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Destination</th>
            <th>Type</th>
            <th>Plat</th>
            <th>Departs</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>7:35am</td>
            <td>East Pakenham</td>
            <td>Express</td>
            <td>2</td>
            <td><span class="pid-badge">9:42 am</span></td>
          </tr>
        </tbody>
      </table>
    </div>
    
  </div>
  
  <!-- Spacer before title bar -->
  <div class="pid-spacer"></div>
</div>

<!-- TRMNL Native Title Bar -->
<div class="title_bar">
  <img class="image" src="https://cdn.getminted.cc/transitvic_black.png" />
  <span class="title">Transit Victoria</span>
  <span class="instance">Updated 7:23 am</span>
</div>