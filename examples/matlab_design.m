function product = matlab_design()
% Example MATLAB design description for EMC Analyzer.
%  - Open directly (needs MATLAB Engine for Python), or
%  - run in MATLAB and save:  product = matlab_design(); save('matlab_design.mat','product');
%    then open the .mat file (needs only scipy).
product.name = 'Motor drive (MATLAB model)';
product.platform = 'AGV';
product.standards = {'CISPR32_A_RE', 'CISPR32_A_CE_QP'};

product.enclosure.name = 'Steel cabinet';
product.enclosure.material = 'steel';
product.enclosure.thickness_m = 1.2e-3;
product.enclosure.dimensions_m = [0.4 0.3 0.15];
product.enclosure.apertures(1).name = 'Fan grille';
product.enclosure.apertures(1).length_m = 0.08;
product.enclosure.apertures(1).count = 1;

c.name = 'INVERTER';
c.type = 'motor_drive';
c.supply_voltage = 48;
c.input_current_a = 8;
c.switch_node_to_chassis_f = 80e-12;
c.power_cable = 'MOTOR_PWR';
c.sources(1).name = 'PHASE_U';
c.sources(1).kind = 'pwm';
c.sources(1).frequency = 20e3;
c.sources(1).amplitude_v = 48;
c.sources(1).rise_time = 50e-9;
c.sources(1).duty = 0.5;
c.sources(1).current_a = 10;
c.loops(1).name = 'DC_LINK';
c.loops(1).source = 'PHASE_U';
c.loops(1).area_m2 = 4e-4;
product.circuits = c;

product.cables(1).name = 'MOTOR_PWR';
product.cables(1).length_m = 2;
product.cables(1).shielded = false;
product.cables(1).connected_circuit = 'INVERTER';
end
